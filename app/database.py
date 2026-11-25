import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.schemas import TERMINAL, Job, JobRequest, Status


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction(write=True) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS job_queue ON jobs(status, created)")

    @staticmethod
    def lookup(conn: sqlite3.Connection, job_id: str) -> Job | None:
        match = conn.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(match[0]) if match else None

    @staticmethod
    def save(conn: sqlite3.Connection, job: Job, **updates) -> Job:
        result = job.model_copy(update={"updated_at": datetime.now(UTC), **updates})
        conn.execute("UPDATE jobs SET status = ?, payload = ? WHERE id = ?",
                     (result.status, result.model_dump_json(), result.job_id))
        if result.status != job.status and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='run_events'"
        ).fetchone():
            conn.execute("""INSERT INTO run_events(run_id,stage,at)
                         SELECT id,?,? FROM runs WHERE job_id=?""",
                         (result.status, result.updated_at.isoformat(), job.job_id))
        return result

    def create(self, request: JobRequest) -> Job:
        now = datetime.now(UTC)
        job = Job(job_id=uuid4().hex, request=request, status=Status.QUEUED, progress=0,
                  created_at=now, updated_at=now)
        with self.transaction(write=True) as conn:
            conn.execute("INSERT INTO jobs VALUES (?, ?, ?, ?)",
                         (job.job_id, job.status, now.isoformat(), job.model_dump_json()))
        return job

    def get(self, job_id: str) -> Job | None:
        with self.transaction() as conn:
            return self.lookup(conn, job_id)

    def list(self, limit: int) -> list[Job]:
        with self.transaction() as conn:
            rows = conn.execute("SELECT payload FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]

    def claim(self) -> Job | None:
        with self.transaction(write=True) as conn:
            row = conn.execute("SELECT payload FROM jobs WHERE status = ? ORDER BY created LIMIT 1",
                               (Status.QUEUED,)).fetchone()
            if row:
                job = Job.model_validate_json(row[0])
                return self.save(conn, job, status=Status.PROBING, progress=1, started_at=datetime.now(UTC))
            return None

    def advance(self, job_id: str, status: Status, progress: int, **updates) -> None:
        with self.transaction(write=True) as conn:
            job = self.lookup(conn, job_id)
            if job and job.status not in TERMINAL:
                self.save(conn, job, status=status, progress=max(job.progress, progress), **updates)

    def finish(self, job_id: str, status: Status, **updates) -> None:
        with self.transaction(write=True) as conn:
            job = self.lookup(conn, job_id)
            if job and job.status not in TERMINAL:
                if job.cancel_requested:
                    status = Status.CANCELLED
                    updates.pop("error", None)
                progress = 100 if status in {Status.COMPLETED, Status.WARNINGS} else job.progress
                self.save(conn, job, status=status, progress=progress, finished_at=datetime.now(UTC), **updates)

    def cancel(self, job_id: str) -> Job | None:
        with self.transaction(write=True) as conn:
            job = self.lookup(conn, job_id)
            if not job or job.status in TERMINAL or job.cancel_requested:
                return job
            if job.status == Status.QUEUED:
                return self.save(conn, job, status=Status.CANCELLED,
                                 finished_at=datetime.now(UTC), cancel_requested=True)
            return self.save(conn, job, cancel_requested=True)

    def recover_interrupted(self) -> None:
        with self.transaction(write=True) as conn:
            statuses = [status for status in Status if status != Status.QUEUED and status not in TERMINAL]
            placeholders = ", ".join("?" for _ in statuses)
            rows = conn.execute(f"SELECT payload FROM jobs WHERE status IN ({placeholders})", statuses).fetchall()
            for row in rows:
                job = Job.model_validate_json(row[0])
                status = Status.CANCELLED if job.cancel_requested else Status.FAILED
                error = None if job.cancel_requested else "Backend stopped during processing. Submit a new job to retry."
                self.save(conn, job, status=status, error=error, finished_at=datetime.now(UTC))
