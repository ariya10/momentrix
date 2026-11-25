"""Versioned clip drafts, review decisions, and immutable render jobs."""

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import Field, StringConstraints, model_validator

from app.api.routes import find_clip, read_clips
from app.schemas import Campaign, Clip, Job, PublishingMetadata, Review, StrictModel, Transcript
from app.services import audio
from app.services.campaigns import load_campaign
from app.services.clip_validator import includes, metadata_issues, transcript_text
from app.utils.files import child, source_path, write_json
from app.v2.assets import asset_record
from app.v2.editing import TRACK_LAYOUTS, EditDecision, default_decision, render_revision
from app.v2.storage import now, uid
from app.v2.presets import processing_settings
from app.v2.tracking import track_points

router = APIRouter()
PUBLIC_ID = r"^[0-9a-f]{32}:clip_[0-9]{2}$"
ClipId = Annotated[str, StringConstraints(pattern=PUBLIC_ID)]


class Draft(StrictModel):
    revision: int = Field(ge=1)
    edit: EditDecision
    metadata: PublishingMetadata | None = None


class SuggestionRequest(StrictModel):
    revision: int = Field(ge=1)


class ReviewDecision(Review):
    revision: int = Field(ge=1)


class Batch(StrictModel):
    clip_ids: list[ClipId] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(self.clip_ids) != len(set(self.clip_ids)):
            raise ValueError("Duplicate clip IDs in this export")
        return self


class ExportStart(Batch):
    export_id: str = Field(pattern=r"^[0-9a-f]{32}$")


RUN_SELECT = """SELECT r.id,r.project_id,r.asset_id,r.campaign,p.name,p.authorized,
                       a.stored_name,a.metadata,j.payload
                FROM runs r JOIN projects p ON p.id=r.project_id
                JOIN assets a ON a.id=r.asset_id AND a.project_id=p.id
                JOIN jobs j ON j.id=r.job_id
                WHERE j.status IN ('completed','completed_with_warnings')"""


@dataclass
class ClipContext:
    row: object
    job: Job
    clip: Clip
    folder: Path

    @property
    def id(self):
        return f"{self.row['id']}:{self.clip.clip_id}"


def load_context(settings, db, clip_id):
    if not re.fullmatch(PUBLIC_ID, clip_id):
        raise HTTPException(404, "Clip not found")
    run_id, name = clip_id.split(":")
    with db.transaction() as conn:
        row = conn.execute(RUN_SELECT + " AND r.id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Completed run not found")
    job = Job.model_validate_json(row["payload"])
    folder = child(settings.root / "output", job.job_id)
    _, clip = find_clip(read_clips(folder), name)
    return ClipContext(row, job, clip, folder)


def revision(conn, ctx):
    record = conn.execute("SELECT * FROM revisions WHERE clip_id=?", (ctx.id,)).fetchone()
    if record:
        return dict(record)
    return {"version": 1, "draft": None, "preview": None, "final": None,
            "review": "pending", "reviewed_at": None, "note": "", "metadata": None}


def initialize_revision(conn, ctx):
    conn.execute("INSERT OR IGNORE INTO revisions(clip_id,version,review) VALUES (?,1,'pending')", (ctx.id,))
    return revision(conn, ctx)


def selected_source(settings, ctx):
    return source_path(settings.root / "input", ctx.row["stored_name"], settings.max_input_bytes)


def source_info(settings, ctx):
    stored = json.loads(ctx.row["metadata"])
    if all(key in stored for key in audio.Media.__dataclass_fields__):
        return audio.Media(**{key: stored[key] for key in audio.Media.__dataclass_fields__})
    # V1 persisted media details in reports, and source files may still be used for edits.
    try:
        return audio.probe(settings, selected_source(settings, ctx), lambda: None)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, "The original source is unavailable for editing") from exc


def decision(settings, ctx, rev):
    if rev["draft"]:
        return EditDecision.model_validate_json(rev["draft"])
    return default_decision(ctx.clip, ctx.job.request, source_info(settings, ctx))


def current_metadata(ctx, rev):
    if rev["metadata"]:
        return PublishingMetadata.model_validate_json(rev["metadata"])
    return PublishingMetadata.model_validate(ctx.clip.model_dump(include=set(PublishingMetadata.model_fields)))


def describe(ctx, rev):
    return {**ctx.clip.model_dump(mode="json"), **current_metadata(ctx, rev).model_dump(),
            "id": ctx.id, "asset_id": ctx.row["asset_id"],
            "project_name": ctx.row["name"], "project_id": ctx.row["project_id"],
            "campaign": ctx.job.request.campaign, "revision": rev["version"],
            "exported": bool(rev["final"] and rev["review"] == "approved"),
            "review": {"status": rev["review"], "note": rev["note"]}, "reviewed_at": rev["reviewed_at"],
            "rendered_preview": f"/api/v2/clips/{ctx.id}/preview-media?v={rev['version']}" if rev["preview"] else None}


def list_catalog(settings, db, project_id=None):
    query = RUN_SELECT
    args = ()
    if project_id is not None:
        query += " AND p.id=?"
        args = (project_id,)
    with db.transaction() as conn:
        if project_id is not None and not conn.execute("SELECT 1 FROM projects WHERE id=?", args).fetchone():
            raise HTTPException(404, "Project not found")
        rows = conn.execute(query + " ORDER BY j.created DESC", args).fetchall()
        result = []
        for row in rows:
            job = Job.model_validate_json(row["payload"])
            folder = child(settings.root / "output", job.job_id)
            for candidate in read_clips(folder):
                ctx = ClipContext(row, job, candidate, folder)
                result.append(describe(ctx, revision(conn, ctx)))
        return result


@router.get("/clips")
def clips(request: Request):
    return list_catalog(request.app.state.settings, request.app.state.database)


@router.get("/projects/{project_id}/clips")
def project_clips(project_id: str, request: Request):
    return list_catalog(request.app.state.settings, request.app.state.database, project_id)


def context(request, clip_id):
    state = request.app.state
    return state, load_context(state.settings, state.database, clip_id)


@router.get("/clips/{clip_id}")
def get_clip(clip_id: str, request: Request):
    state, ctx = context(request, clip_id)
    with state.database.transaction() as conn:
        rev = revision(conn, ctx)
    edit = decision(state.settings, ctx, rev)
    hooks = [current_metadata(ctx, rev).hook]
    speech = transcript(ctx)
    for segment in speech.segments:
        if any(span.start <= segment.start < segment.end <= span.end for span in edit.kept_spans()):
            line = " ".join(segment.text.split())
            if 3 <= len(line.split()) and len(line) <= 100 and line.casefold() not in {h.casefold() for h in hooks}:
                hooks.append(line)
        if len(hooks) >= 5:
            break
    result = {**describe(ctx, rev), "edit": edit.model_dump(mode="json"), "hook_options": hooks}
    kind = "preview" if rev["preview"] else "export" if rev["final"] else None
    if kind and edit.layout in TRACK_LAYOUTS:
        report = child(render_folder(state.settings, ctx.id, rev["version"], kind), "report.json")
        if report.is_file():
            result["rendered_layout"] = json.loads(report.read_bytes()).get("rendered_layout")
    return result


def transcript(ctx):
    try:
        return Transcript.model_validate_json(child(ctx.folder, "transcript.json").read_bytes())
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Source transcript is unavailable") from exc


@router.get("/clips/{clip_id}/transcript")
def clip_transcript(clip_id: str, request: Request):
    _, ctx = context(request, clip_id)
    return transcript(ctx)


def expected(rev, version):
    if rev["version"] != version:
        raise HTTPException(409, "This clip changed. Reload the current revision.")


@router.patch("/clips/{clip_id}")
def save_clip(clip_id: str, data: Draft, request: Request):
    state, ctx = context(request, clip_id)
    media = source_info(state.settings, ctx)
    if data.edit.end_seconds > media.duration + 0.001:
        raise HTTPException(422, "Selection extends beyond the source duration")
    if data.edit.layout in TRACK_LAYOUTS and not track_points(
        state.settings, asset_record(state.database, ctx.row["asset_id"]), data.edit.track_id,
    ):
        raise HTTPException(422, "The selected sampled face track is unavailable")
    try:
        for region in (data.edit.roi, data.edit.facecam, data.edit.gameplay):
            if region:
                region.pixels(media)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with state.database.transaction(write=True) as conn:
        rev = initialize_revision(conn, ctx)
        expected(rev, data.revision)
        previous = EditDecision.model_validate_json(rev["draft"]) if rev["draft"] else default_decision(ctx.clip, ctx.job.request, media)
        updated_metadata = data.metadata is not None and data.metadata != current_metadata(ctx, rev)
        if data.edit != previous or updated_metadata:
            metadata = data.metadata.model_dump_json() if updated_metadata else rev["metadata"]
            conn.execute("""UPDATE revisions SET version=version+1,draft=?,metadata=?,review='pending',reviewed_at=NULL,
                         note='',preview=NULL,final=NULL WHERE clip_id=?""", (data.edit.model_dump_json(), metadata, ctx.id))
            conn.execute("INSERT INTO reviews(clip_id,version,status,at,note) VALUES(?,?,'edited',?,?)",
                         (ctx.id, data.revision+1, now(), json.dumps({"edit": data.edit.model_dump(),
                                                                  "metadata": json.loads(metadata) if metadata else None})))
        rev = revision(conn, ctx)
    return {**describe(ctx,rev), "edit":data.edit.model_dump(mode="json")}


def clip_campaign(settings, ctx):
    return (Campaign.model_validate_json(ctx.row["campaign"]) if ctx.row["campaign"]
            else load_campaign(settings.root,ctx.job.request.campaign))


def validate_campaign(settings, ctx, edit, rev):
    if not ctx.row["authorized"]:
        raise HTTPException(409, "Source authorization is required for export")
    campaign = clip_campaign(settings, ctx)
    if not campaign.min_duration - .001 <= edit.duration <= campaign.max_duration + .001:
        raise HTTPException(422, "Edited duration falls outside the campaign limits")
    metadata = current_metadata(ctx, rev)
    issues = metadata_issues(metadata.model_copy(update={"hook": edit.hook or metadata.hook}),campaign)
    if campaign.required_keywords:
        speech = transcript(ctx)
        text = " ".join(transcript_text(speech, span.start, span.end) for span in edit.kept_spans())
        issues.extend(f"Missing spoken keyword {term}" for term in campaign.required_keywords if not includes(text,term))
    if issues:
        raise HTTPException(422, ". ".join(issues))


@router.post("/clips/{clip_id}/review")
def review_clip(clip_id: str, data: ReviewDecision, request: Request):
    state, ctx = context(request, clip_id)
    with state.database.transaction() as conn:
        snapshot = revision(conn, ctx)
    expected(snapshot, data.revision)
    if data.status == "approved":
        if snapshot["draft"] and not snapshot["preview"]:
            raise HTTPException(409, "Render the saved draft preview before approving this revision")
        validate_campaign(state.settings, ctx, decision(state.settings, ctx, snapshot), snapshot)
    with state.database.transaction(write=True) as conn:
        rev = initialize_revision(conn, ctx)
        expected(rev, data.revision)
        timestamp = now()
        conn.execute("""UPDATE revisions SET review=?,reviewed_at=?,note=?,
                     final=CASE WHEN ?='approved' THEN final ELSE NULL END WHERE clip_id=?""",
                     (data.status,timestamp,data.note,data.status,ctx.id))
        conn.execute("INSERT INTO reviews(clip_id,version,status,at,note) VALUES(?,?,?,?,?)",
                     (ctx.id,data.revision,data.status,timestamp,data.note))
        return describe(ctx,revision(conn,ctx))


def render_folder(settings, clip_id, version, kind):
    run_id, name = clip_id.split(":")
    folder = child(settings.root / "storage", "exports")
    for part in (run_id, name, str(version), kind):
        folder = child(folder,part)
    return folder


def media_file(path, filename=None):
    if path.resolve() != path.absolute() or not path.is_file():
        raise HTTPException(404, "Media file is unavailable")
    return FileResponse(path, media_type="video/mp4", filename=filename,
                        content_disposition_type="attachment" if filename else "inline")


@router.get("/clips/{clip_id}/media")
def media(clip_id: str, request: Request):
    state, ctx = context(request, clip_id)
    with state.database.transaction() as conn:
        rev = revision(conn,ctx)
    if rev["preview"]:
        return media_file(child(render_folder(state.settings,ctx.id,rev["version"],"preview"),"clip.mp4"))
    return media_file(child(ctx.folder,ctx.clip.file))


@router.get("/clips/{clip_id}/preview-media")
def preview_media(clip_id: str, request: Request, v: int | None = None):
    state, ctx = context(request, clip_id)
    with state.database.transaction() as conn:
        rev = revision(conn,ctx)
    if not rev["preview"] or (v is not None and rev["version"] != v):
        raise HTTPException(409, "This preview is unavailable for the current revision")
    return media_file(child(render_folder(state.settings,ctx.id,rev["version"],"preview"),"clip.mp4"))


@router.get("/clips/{clip_id}/download")
def download(clip_id: str, request: Request):
    state, ctx = context(request, clip_id)
    with state.database.transaction() as conn:
        rev = revision(conn,ctx)
    if not rev["final"] or rev["review"] != "approved":
        raise HTTPException(409, "This revision needs an approved final render")
    folder = render_folder(state.settings,ctx.id,rev["version"],"export")
    return media_file(child(folder,"clip.mp4"), f"{ctx.clip.clip_id}-v{rev['version']}.mp4")


class ZipBuffer:
    """Forward-only writer for a ZIP response. Drain between file blocks."""

    def __init__(self):
        self.data = bytearray()
        self.offset = 0

    def tell(self):
        return self.offset

    def write(self, block):
        self.data.extend(block)
        self.offset += len(block)
        return len(block)

    def flush(self):
        pass

    def drain(self):
        block = bytes(self.data)
        self.data.clear()
        return block


def package_files(settings, clip_id, version, task_id, include_media):
    folder = render_folder(settings,clip_id,version,"export")
    prefix = f"{clip_id.replace(':','-')}-v{version}/"
    entries = [(name,name) for name in ("captions.srt","captions.vtt","captions.ass","edit.json","report.json")]
    entries.append((f"metadata-{task_id}.json","metadata.json"))
    if include_media:
        entries.append(("clip.mp4","clip.mp4"))
    files = []
    for name,archive_name in entries:
        path = child(folder,name)
        if not path.is_file() or path.resolve() != path.absolute():
            raise HTTPException(409,f"The checked export is missing {archive_name}")
        files.append((path,prefix+archive_name))
    return files


def stream_zip(files):
    sink = ZipBuffer()
    with zipfile.ZipFile(sink,"w",compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
        for path,name in files:
            with path.open("rb") as source, archive.open(name,"w",force_zip64=True) as target:
                while block := source.read(1024*1024):
                    target.write(block)
                    yield sink.drain()
            yield sink.drain()
    yield sink.drain()


def zip_response(files,name):
    return StreamingResponse(stream_zip(files),media_type="application/zip",
                             headers={"Content-Disposition":f'attachment; filename="{name}.zip"'})


@router.get("/clips/{clip_id}/package")
def download_metadata(clip_id: str, request: Request):
    state,ctx = context(request,clip_id)
    with state.database.transaction() as conn:
        rev = revision(conn,ctx)
    if rev["review"] != "approved" or not rev["final"]:
        raise HTTPException(409,"An approved final render is required")
    files = package_files(state.settings,ctx.id,rev["version"],rev["final"],False)
    return zip_response(files, f"{ctx.clip.clip_id}-v{rev['version']}-metadata")


def task_view(row):
    items = json.loads(row["payload"])["items"]
    return {"id": row["id"], "status": row["status"], "kind": row["kind"], "error": row["error"],
            "clip_ids": [item["clip_id"] for item in items], "created_at": row["created_at"]}


def metadata_task(conn, clip_id, revision_number):
    return conn.execute("""SELECT * FROM tasks WHERE kind='metadata'
                        AND json_extract(payload,'$.items[0].clip_id')=?
                        AND json_extract(payload,'$.items[0].revision')=?
                        ORDER BY created_at DESC LIMIT 1""", (clip_id, revision_number)).fetchone()


@router.get("/clips/{clip_id}/metadata/suggestion")
def read_metadata_suggestion(clip_id: str, request: Request):
    state, ctx = context(request, clip_id)
    with state.database.transaction() as conn:
        row = metadata_task(conn, ctx.id, revision(conn, ctx)["version"])
    if row is None:
        return None
    return {**task_view(row), "suggestion": json.loads(row["payload"]).get("suggestion")}


@router.post("/clips/{clip_id}/metadata/suggestion", status_code=202)
def request_metadata_suggestion(clip_id: str, data: SuggestionRequest, request: Request):
    state, ctx = context(request, clip_id)
    if not ctx.row["authorized"]:
        raise HTTPException(409, "Source authorization is required")
    with state.database.transaction(write=True) as conn:
        expected(revision(conn, ctx), data.revision)
        row = metadata_task(conn, ctx.id, data.revision)
        if row is not None and row["status"] in {"queued", "working"}:
            return task_view(row)
        task_id = uid()
        payload = json.dumps({"items": [{"clip_id": ctx.id, "revision": data.revision}]})
        conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?,NULL)", (task_id, "metadata", payload, "queued", now()))
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    state.worker.wake.set()
    return task_view(row)


def process_metadata(settings, db, row, cancel):
    from app.v2.metadata import suggest

    payload = json.loads(row["payload"])
    item = payload["items"][0]
    ctx = load_context(settings, db, item["clip_id"])
    with db.transaction() as conn:
        rev = revision(conn, ctx)
    expected(rev, item["revision"])
    if payload.get("suggestion"):
        return
    edit = decision(settings, ctx, rev)
    speech = transcript(ctx)
    spans = edit.kept_spans()
    lines = [transcript_text(speech, span.start, span.end) for span in spans]
    events = [event for event in ctx.clip.evidence
              if any(span.start <= event.start <= event.end <= span.end for span in spans)]
    proposal = suggest(settings, lines, events, clip_campaign(settings, ctx), cancel)
    cancel()
    payload["suggestion"] = proposal.model_dump(mode="json")
    with db.transaction(write=True) as conn:
        expected(revision(conn, ctx), item["revision"])
        conn.execute("UPDATE tasks SET payload=? WHERE id=? AND status='working'",
                     (json.dumps(payload), row["id"]))


def find_task(conn, task_id, *, internal=False):
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None or row["kind"] not in ({"export"} if internal else {"preview", "export"}):
        raise HTTPException(404, "Render job not found")
    return row


def check_snapshot(rev, item, *, final):
    expected(rev, item["revision"])
    if final and (rev["review"] != "approved" or rev["reviewed_at"] != item["approval"]):
        raise HTTPException(409, "The requested export no longer has its original approval")


def send_export(state, task_id, clip_ids):
    from app.v2.runs import dispatch_webhook

    try:
        dispatch_webhook(state.settings, "export", {"export_id":task_id,"clip_ids":clip_ids})
    except ValueError as exc:
        with state.database.transaction(write=True) as conn:
            conn.execute("""UPDATE tasks SET status='failed',error=?
                         WHERE id=? AND status='awaiting_automation'""", (str(exc),task_id))


def schedule(request, clip_ids, kind, background):
    state = request.app.state
    final = kind == "export"
    items = []
    contexts = [load_context(state.settings, state.database, key) for key in clip_ids]
    for ctx in contexts:
        with state.database.transaction() as conn:
            rev = revision(conn, ctx)
        if not ctx.row["authorized"]:
            raise HTTPException(409,"Confirm authorization before rendering the source")
        if final and rev["review"] != "approved":
            raise HTTPException(409, "Every clip in this export requires approval of the current revision")
        edit = decision(state.settings, ctx, rev)
        if final:
            validate_campaign(state.settings,ctx,edit,rev)
        item = {"clip_id":ctx.id, "revision":rev["version"],
                "edit":edit.model_dump(mode="json", exclude={"track_id"} if edit.track_id is None else None),
                "approval":rev["reviewed_at"] if final else None}
        if edit.layout in TRACK_LAYOUTS:
            item["track_points"] = track_points(state.settings, asset_record(state.database, ctx.row["asset_id"]),
                                               edit.track_id)
        items.append(item)

    payload = json.dumps({"items":items}, sort_keys=True)
    with state.database.transaction(write=True) as conn:
        published = True
        for item,ctx in zip(items,contexts):
            rev = initialize_revision(conn,ctx)
            check_snapshot(rev,item,final=final)
            published &= bool(rev["final" if final else "preview"])
        duplicate = conn.execute("""SELECT * FROM tasks WHERE kind=? AND payload=? AND
                                 (status IN ('awaiting_automation','queued','working') OR (? AND status='completed'))
                                 ORDER BY created_at DESC LIMIT 1""", (kind,payload,published)).fetchone()
        if duplicate:
            return task_view(duplicate)
        task_id = uid()
        conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?,NULL)",
                     (task_id,kind,payload,"awaiting_automation" if final else "queued",now()))
        result = task_view(find_task(conn,task_id))
    if final:
        background.add_task(send_export,state,task_id,clip_ids)
    else:
        state.worker.wake.set()
    return result


@router.post("/clips/{clip_id}/preview",status_code=202)
def render_preview(clip_id: str, request: Request, background: BackgroundTasks):
    return schedule(request,[clip_id],"preview",background)


@router.post("/clips/{clip_id}/render",status_code=202)
def render_final(clip_id: str, request: Request, background: BackgroundTasks):
    return schedule(request,[clip_id],"export",background)


@router.post("/exports",status_code=202)
def export_batch(batch: Batch, request: Request, background: BackgroundTasks):
    return schedule(request,batch.clip_ids,"export",background)


@router.get("/exports/{task_id}")
def get_render(task_id: str, request: Request):
    with request.app.state.database.transaction() as conn:
        return task_view(find_task(conn,task_id))


@router.get("/exports/{task_id}/download")
def download_batch(task_id: str, request: Request):
    state = request.app.state
    files = []
    with state.database.transaction() as conn:
        row = find_task(conn,task_id,internal=True)
        if row["status"] != "completed":
            raise HTTPException(409,"Wait for the approved export to finish")
        for item in json.loads(row["payload"])["items"]:
            rev = conn.execute("SELECT * FROM revisions WHERE clip_id=?",(item["clip_id"],)).fetchone()
            check_snapshot(rev,item,final=True)
            files.extend(package_files(state.settings,item["clip_id"],item["revision"],row["id"],True))
    return zip_response(files,f"momentrix-{task_id}")


@router.get("/internal/exports/{task_id}")
def automation_export(task_id: str, request: Request):
    with request.app.state.database.transaction() as conn:
        return task_view(find_task(conn,task_id,internal=True))


@router.post("/internal/exports/{task_id}/start",status_code=202)
def start_export(task_id: str, data: ExportStart, request: Request):
    if data.export_id != task_id:
        raise HTTPException(409,"Export ID does not match this callback")
    state = request.app.state
    stale = None
    with state.database.transaction(write=True) as conn:
        row = find_task(conn, task_id, internal=True)
        if task_view(row)["clip_ids"] != data.clip_ids:
            raise HTTPException(409,"Clip IDs do not match this export")
        if row["status"] == "awaiting_automation":
            try:
                for item in json.loads(row["payload"])["items"]:
                    rev = conn.execute("SELECT * FROM revisions WHERE clip_id=?",(item["clip_id"],)).fetchone()
                    check_snapshot(rev,item,final=True)
            except HTTPException as exc:
                stale = exc
                conn.execute("UPDATE tasks SET status='cancelled',error=? WHERE id=?",(exc.detail,task_id))
            else:
                conn.execute("UPDATE tasks SET status='queued' WHERE id=?", (task_id,))
        elif row["status"] == "cancelled":
            stale = HTTPException(409, row["error"] or "Export was cancelled")
        result = task_view(find_task(conn,task_id))
    if stale:
        raise stale
    state.worker.wake.set()
    return result


def process_render(settings, db, row, cancel):
    """Run inside the sole media worker. Publish database pointers only for the complete current batch."""
    final = row["kind"] == "export"
    items = json.loads(row["payload"])["items"]
    try:
        for item in items:
            cancel()
            ctx = load_context(settings,db,item["clip_id"])
            with db.transaction() as conn:
                rev = revision(conn, ctx)
                check_snapshot(rev,item,final=final)
            if not ctx.row["authorized"]:
                raise ValueError("Source authorization is missing")
            edit = EditDecision.model_validate(item["edit"])
            if final:
                validate_campaign(settings,ctx,edit,rev)
            target = render_folder(settings,ctx.id,item["revision"],row["kind"])
            render_settings = processing_settings(settings, ctx.job.request.processing_preset)
            path = render_revision(render_settings,selected_source(settings,ctx),transcript(ctx),edit,target,
                                   preview=not final,track_points=item.get("track_points"),cancel=cancel)
            if final:
                metadata = current_metadata(ctx, rev)
                manifest = {
                    "clip_id":ctx.id, "project_id":ctx.row["project_id"], "revision":item["revision"],
                    "approved_at":item["approval"], "title":metadata.title, "caption":metadata.caption,
                    "hook":edit.hook or metadata.hook, "description":metadata.description,
                    "hashtags":metadata.hashtags, "campaign":ctx.job.request.campaign}
                if rev["metadata"]:
                    manifest.update(instagram_caption=metadata.instagram_caption,
                                    tiktok_caption=metadata.tiktok_caption, thumbnail_text=metadata.thumbnail_text)
                metadata_file = child(path.parent,f"metadata-{row['id']}.json")
                if not metadata_file.exists():
                    write_json(metadata_file,manifest)
                elif json.loads(metadata_file.read_bytes()) != manifest:
                    raise ValueError("The stored export manifest belongs to different metadata")
        cancel()
        with db.transaction(write=True) as conn:
            for item in items:
                rev = conn.execute("SELECT * FROM revisions WHERE clip_id=?",(item["clip_id"],)).fetchone()
                check_snapshot(rev,item,final=final)
            for item in items:
                column = "final" if final else "preview"
                conn.execute(f"UPDATE revisions SET {column}=? WHERE clip_id=?",
                             (row["id"],item["clip_id"]))
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
