import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from urllib.parse import unquote

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.schemas import ProcessingPreset
from app.services.audio import probe
from app.utils.files import child, source_path, video_name
from app.v2.storage import now, uid


def inspect_source(settings, path):
    media = probe(settings, path, lambda: None)
    if media.duration > settings.max_source_seconds:
        raise ValueError("Source exceeds the duration limit")
    return asdict(media)


def present_asset(row):
    return {"id":row["id"],"project_id":row["project_id"],"filename":row["filename"],**json.loads(row["metadata"])}


def asset_record(db, asset_id):
    with db.transaction() as c:
        row = c.execute("""SELECT a.*, p.content_type FROM assets a
                           JOIN projects p ON p.id=a.project_id WHERE a.id=?""", (asset_id,)).fetchone()
    if not row:
        raise HTTPException(404,"Asset not found")
    return row


def finish_import(settings, db, project_id, tmp, filename, digest, preset: ProcessingPreset = "balanced"):
    media = inspect_source(settings, tmp)
    media["processing_preset"] = preset
    if project_id is None:
        media["scheduled_import"] = True
    stored = f"mx-{digest}{tmp.suffix.lower()}"
    target = child(settings.root / "input", stored)
    with db.transaction(write=True) as c:
        if project_id is None:
            existing = c.execute("SELECT * FROM assets WHERE digest=? LIMIT 1", (digest,)).fetchone()
        else:
            existing = c.execute("SELECT * FROM assets WHERE project_id=? AND digest=?",(project_id,digest)).fetchone()
        if existing:
            return present_asset(existing), False
        if project_id is None:
            project_id = uid()
            c.execute("INSERT INTO projects VALUES (?,?, 'general', 1, ?, 0)",
                      (project_id, Path(filename).stem[:120], now()))
        try:
            os.link(tmp,target)
        except FileExistsError:
            with target.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                    raise ValueError("Stored source fingerprint no longer matches its name")
        except OSError:
            # Fallback for cross-device links or sandbox restrictions.
            if not target.exists():
                shutil.copy2(tmp, target)
        asset_id = uid()
        c.execute("INSERT INTO assets VALUES (?,?,?,?,?,?)",
                  (asset_id,project_id,filename,stored,digest,json.dumps(media)))
        c.execute("INSERT INTO tasks VALUES (?,?,?,'queued',?,NULL)",
                  (uid(),"prepare_asset",json.dumps({"asset_id":asset_id}),now()))
        return present_asset(c.execute("SELECT * FROM assets WHERE id=?",(asset_id,)).fetchone()), True


def copy_local(settings,db,project_id,filename,preset: ProcessingPreset = "balanced", *, cancel=lambda: None):
    source = source_path(settings.root/"input",filename,settings.max_input_bytes)
    if source.stat().st_size + settings.minimum_free_bytes > shutil.disk_usage(settings.root).free:
        raise HTTPException(413,"Insufficient disk space to ingest this asset")
    with TemporaryDirectory(dir=settings.root/"cache") as tmp:
        path = Path(tmp)/("source"+source.suffix.lower())
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as inp, path.open("xb") as out:
            while block := inp.read(1024*1024):
                cancel()
                size += len(block)
                if size > settings.max_input_bytes:
                    raise HTTPException(413,"Source exceeds the upload limit")
                digest.update(block)
                out.write(block)
        return finish_import(settings,db,project_id,path,filename,digest.hexdigest(),preset)


async def ingest(request: Request, project_id, preset: ProcessingPreset):
    settings,db = request.app.state.settings,request.app.state.database
    with db.transaction() as c:
        row = c.execute("SELECT authorized,legacy FROM projects WHERE id=?",(project_id,)).fetchone()
    if not row:
        raise HTTPException(404,"Project not found")
    if not row[0] or row[1]:
        raise HTTPException(409,"Use an authorized V2 project to import a source")
    try:
        if request.headers.get("content-type","").split(";")[0]=="application/json":
            data = await request.json()
            if not isinstance(data,dict) or not isinstance(data.get("filename"),str):
                raise HTTPException(422,"A local filename is required")
            asset, _ = await run_in_threadpool(copy_local,settings,db,project_id,data["filename"],preset)
            return asset
        filename = video_name(unquote(request.headers.get("x-filename",""),errors="strict"))
        limit = min(settings.max_input_bytes,shutil.disk_usage(settings.root).free-settings.minimum_free_bytes)
        if int(request.headers.get("content-length") or 0)>limit:
            raise HTTPException(413,"Upload exceeds available disk space or the configured limit")
        with TemporaryDirectory(dir=settings.root/"cache") as tmp:
            path = Path(tmp)/("source"+Path(filename).suffix.lower())
            digest = hashlib.sha256()
            size = 0
            with path.open("xb") as out:
                async for block in request.stream():
                    size += len(block)
                    if size>limit:
                        raise HTTPException(413,"Upload exceeds available disk space or the configured limit")
                    digest.update(block)
                    await run_in_threadpool(out.write,block)
            asset, _ = await run_in_threadpool(finish_import,settings,db,project_id,path,filename,digest.hexdigest(),preset)
            return asset
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(422,f"Could not ingest the source. {exc}") from exc

