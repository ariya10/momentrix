from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.config import ROOT
from app.schemas import Job
from app.services.campaigns import directory, load_campaign


def now():
    return datetime.now(UTC).isoformat()


def uid():
    return uuid4().hex


def migrate(db):
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    with closing(sqlite3.connect(db.path)) as source:
        table = source.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
        if table and source.execute("SELECT version_num FROM alembic_version").fetchone() == (head,):
            return
        backups = db.path.parent / "backups"
        backups.mkdir(exist_ok=True)
        path = backups / f"before-{head}-{uid()}.sqlite3"
        with closing(sqlite3.connect(path)) as backup:
            source.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite backup failed its integrity check")
    engine = create_engine(URL.create("sqlite", database=str(db.path)))
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def secret_file(settings, name):
    path = settings.root / "data" / name
    if not path.exists():
        try:
            with path.open("x", encoding="ascii") as handle:
                handle.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
    return path.read_text(encoding="ascii").strip()


def seed(settings, db):
    with db.transaction(write=True) as c:
        for path in directory(settings.root).glob("*.json"):
            preset = load_campaign(settings.root, path.stem).model_dump()
            c.execute("INSERT OR IGNORE INTO campaign_presets VALUES (?,?)",
                      (path.stem, json.dumps(dict(preset, archived=False, platform="", date_start=None, date_end=None))))
        c.execute("UPDATE tasks SET status='queued',error=NULL WHERE status='working'")
        c.execute("DELETE FROM sessions WHERE expires < unixepoch()")
    sync_legacy(db)
    secret_file(settings, "studio.key")


def sync_legacy(db):
    with db.transaction(write=True) as c:
        rows = c.execute("""SELECT j.payload FROM jobs j LEFT JOIN runs r ON r.job_id=j.id
                         LEFT JOIN run_jobs a ON a.job_id=j.id WHERE r.id IS NULL AND a.job_id IS NULL""").fetchall()
        for row in rows:
            job = Job.model_validate_json(row[0])
            key = job.job_id
            created = job.created_at.isoformat()
            c.execute("INSERT INTO projects VALUES (?,?,?,?,?,1)",
                      (key,job.request.filename,"general",int(job.request.authorized),created))
            asset_id = hashlib.sha256(("legacy:" + key).encode()).hexdigest()[:32]
            c.execute("INSERT INTO assets VALUES (?,?,?,?,NULL,'{}')",
                      (asset_id,key,job.request.filename,job.request.filename))
            c.execute("""INSERT INTO runs(id,project_id,asset_id,correlation_id,idempotency_key,status,
                      created_at,options,job_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                      (key,key,asset_id,key,key,"legacy",created,job.request.model_dump_json(),key))

