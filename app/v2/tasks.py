import json
import logging
from datetime import UTC, datetime
from app.utils.process import Cancelled


def run_next(worker):
    db = worker.database
    with db.transaction(write=True) as c:
        row = c.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return False
        c.execute("UPDATE tasks SET status='working' WHERE id=?",(row["id"],))

    def cancel():
        if worker.stop.is_set():
            raise Cancelled("Service is shutting down")

    try:
        if row["kind"]=="prepare_asset":
            from app.v2.media_assets import prepare_asset
            prepare_asset(worker.settings,db,json.loads(row["payload"])["asset_id"],cancel)
        elif row["kind"] in {"preview","export"}:
            from app.v2.clips import process_render
            process_render(worker.settings,db,row,cancel)
        elif row["kind"] == "metadata":
            from app.v2.clips import process_metadata
            process_metadata(worker.settings, db, row, cancel)
        elif row["kind"] == "ingest_scan":
            from app.v2.ingestion import run_scan
            run_scan(worker.settings, db, row, cancel)
        else:
            raise ValueError("Unknown task type")
        state,error = "completed",None
    except Cancelled as exc:
        state,error = ("queued",None) if worker.stop.is_set() else ("cancelled",str(exc))
    except Exception as exc:
        logging.getLogger("momentrix.tasks").warning("task_failed id=%s kind=%s exception=%s",
                                                     row["id"],row["kind"],type(exc).__name__)
        state,error = "failed",str(exc)[:1800]
    with db.transaction(write=True) as c:
        c.execute("UPDATE tasks SET status=?,error=? WHERE id=? AND status='working'",(state,error,row["id"]))
    return True

