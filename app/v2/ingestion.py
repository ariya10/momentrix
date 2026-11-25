"""Queue allowlisted local ingestion with the same worker used for media jobs."""

import json
import logging

from fastapi import HTTPException

from app.utils.process import Cancelled
from app.v2.assets import copy_local
from app.v2.runs import Generation, create_run, dispatch
from app.v2.storage import now, uid


def scan_view(row):
    data = json.loads(row["payload"])
    return {"id": row["id"], "status": row["status"], "created_at": row["created_at"],
            "imported": data.get("imported", []), "duplicates": data.get("duplicates", 0),
            "errors": data.get("errors", []) + ([row["error"]] if row["error"] else [])}


def queue_scan(db, settings):
    with db.transaction(write=True) as conn:
        prior = conn.execute("""SELECT * FROM tasks WHERE kind='ingest_scan'
                             AND status IN ('queued','working') LIMIT 1""").fetchone()
        if prior is not None:
            return scan_view(prior)
        key = uid()
        payload = {"filenames": list(dict.fromkeys(settings.scheduled_filenames)),
                   "auto_process": settings.scheduled_auto_process, "campaign": settings.scheduled_campaign}
        conn.execute("INSERT INTO tasks VALUES (?, 'ingest_scan', ?, 'queued', ?, NULL)",
                     (key, json.dumps(payload), now()))
        return scan_view(conn.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone())


def run_scan(settings, db, row, cancel):
    payload = json.loads(row["payload"])
    imported, errors, duplicates = [], [], 0
    for filename in payload["filenames"]:
        cancel()
        if filename not in settings.scheduled_filenames:
            continue
        try:
            asset, fresh = copy_local(settings, db, None, filename, cancel=cancel)
            if fresh:
                imported.append(asset["id"])
            else:
                duplicates += 1
            if payload["auto_process"] and settings.scheduled_auto_process and asset.get("scheduled_import"):
                data = Generation(asset_id=asset["id"], idempotency_key=asset["id"],
                                  options={"campaign": payload["campaign"]})
                key, _ = create_run(settings, db, asset["project_id"], data)
                dispatch(settings, db, key)
        except Cancelled:
            raise
        except HTTPException as exc:
            errors.append(f"{filename}: {exc.detail}")
        except (ValueError, OSError, RuntimeError) as exc:
            errors.append(f"{filename}: {exc}")
    payload.update(imported=imported, errors=errors, duplicates=duplicates)
    with db.transaction(write=True) as conn:
        conn.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))
    logging.getLogger("momentrix.ingestion").info("ingest_scan id=%s imported=%s duplicates=%s errors=%s",
                                                 row["id"], len(imported), duplicates, len(errors))
