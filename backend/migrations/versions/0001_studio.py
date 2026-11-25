"""Add V2 studio records alongside V1 jobs."""
from alembic import op

revision = "0001_studio"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for statement in (
        """CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, content_type TEXT NOT NULL,
        authorized INTEGER NOT NULL, created_at TEXT NOT NULL, legacy INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE assets (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        filename TEXT NOT NULL, stored_name TEXT NOT NULL, digest TEXT, metadata TEXT NOT NULL,
        UNIQUE(project_id,digest))""",
        """CREATE TABLE runs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        asset_id TEXT REFERENCES assets(id), correlation_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, options TEXT NOT NULL, campaign TEXT,
        job_id TEXT UNIQUE, error TEXT, execution_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        UNIQUE(project_id,idempotency_key))""",
        """CREATE TABLE run_events (seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
        stage TEXT NOT NULL, at TEXT NOT NULL)""",
        """CREATE INDEX run_events_run ON run_events(run_id, seq)""",
        """CREATE TABLE run_jobs (job_id TEXT PRIMARY KEY REFERENCES jobs(id), run_id TEXT NOT NULL REFERENCES runs(id))""",
        """CREATE TABLE campaign_presets (id TEXT PRIMARY KEY, document TEXT NOT NULL)""",
        """CREATE TABLE revisions (clip_id TEXT PRIMARY KEY, version INTEGER NOT NULL, draft TEXT,
        review TEXT NOT NULL, reviewed_at TEXT, note TEXT NOT NULL DEFAULT '', preview TEXT, final TEXT)""",
        """CREATE TABLE reviews (seq INTEGER PRIMARY KEY, clip_id TEXT NOT NULL, version INTEGER NOT NULL,
        status TEXT NOT NULL, at TEXT NOT NULL, note TEXT NOT NULL)""",
        """CREATE TABLE tasks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, error TEXT)""",
        """CREATE TABLE automation_errors (seq INTEGER PRIMARY KEY, execution_id TEXT, workflow_name TEXT,
        node TEXT, run_id TEXT, summary TEXT NOT NULL, at TEXT NOT NULL)""",
        """CREATE TABLE sessions (digest TEXT PRIMARY KEY, expires REAL NOT NULL)""",
        """CREATE INDEX task_queue ON tasks(status,created_at)""",
    ):
        op.execute(statement)


def downgrade():
    raise RuntimeError("Restore a verified pre-migration backup to return to the older schema.")

