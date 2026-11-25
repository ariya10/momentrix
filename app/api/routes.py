import importlib.util
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from filelock import FileLock, Timeout
from pydantic import TypeAdapter
from starlette.concurrency import run_in_threadpool

from app.schemas import Clip, Job, JobRequest, Metadata, Review, Status, SystemStatus
from app.services.campaigns import directory, load_campaign, resolve_request
from app.services.clip_validator import metadata_issues
from app.services.metadata import export_metadata
from app.services.ollama_client import availability
from app.services.transcription import model_location
from app.utils.files import child, source_path, video_name

router = APIRouter()
CLIPS = TypeAdapter(list[Clip])
READY = {Status.COMPLETED, Status.WARNINGS}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system/status", response_model=SystemStatus)
def system_status(request: Request) -> SystemStatus:
    settings = request.app.state.settings
    installed = importlib.util.find_spec("faster_whisper") is not None
    readable = False
    if installed:
        try:
            readable = (Path(model_location(settings)) / "model.bin").is_file()
        except (ImportError, OSError, ValueError):
            pass
    ollama, available = availability(settings)
    return SystemStatus(
        ffmpeg=shutil.which(settings.executable("ffmpeg")) is not None,
        ffprobe=shutil.which(settings.executable("ffprobe")) is not None,
        whisper_installed=installed, whisper_model_available=readable,
        whisper_model=settings.whisper_model, ollama=ollama, ollama_model_available=available,
        ollama_model=settings.ollama_model, free_disk_bytes=shutil.disk_usage(settings.root).free,
    )


@router.get("/campaigns")
def campaigns(request: Request) -> list[dict]:
    root = request.app.state.settings.root
    result = []
    for path in sorted(directory(root).glob("*.json")):
        try:
            result.append({"id": path.stem, **load_campaign(root, path.stem).model_dump(mode="json")})
        except (ValueError, OSError):
            continue
    return result


@router.get("/sources")
def sources(request: Request) -> list[str]:
    settings = request.app.state.settings
    folder = settings.root / "input"
    result = []
    for candidate in sorted(folder.iterdir()):
        try:
            source_path(folder, candidate.name, settings.max_input_bytes)
            result.append(candidate.name)
        except (ValueError, OSError):
            continue
    return result


@router.post("/sources", status_code=201)
async def upload(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    folder = settings.root / "input"
    try:
        name = video_name(unquote(request.headers.get("X-Filename", ""), errors="strict"))
        path = child(folder, name)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if path.exists():
        raise HTTPException(409, "A source with that name already exists")
    free = shutil.disk_usage(folder).free - settings.minimum_free_bytes
    limit = min(settings.max_input_bytes, max(0, free))
    length = request.headers.get("content-length")
    if length and length.isdecimal() and int(length) > limit:
        raise HTTPException(413, "Upload exceeds the input size or free space limit")
    with NamedTemporaryFile(dir=folder, suffix=".upload", delete=False) as handle:
        temp = Path(handle.name)
        try:
            size = 0
            async for block in request.stream():
                size += len(block)
                if size > limit:
                    raise HTTPException(413, "Upload exceeds the input size or free space limit")
                await run_in_threadpool(handle.write, block)
            if size == 0:
                raise HTTPException(400, "Upload is empty")
            handle.close()
            try:
                os.link(temp, path)  # Publish the complete upload, with no overwrite race.
            except FileExistsError as exc:
                raise HTTPException(409, "A source with that name already exists") from exc
            except OSError:
                # Fallback for cross-device links or sandbox restrictions.
                try:
                    shutil.copy2(temp, path)
                except FileExistsError as exc:
                    raise HTTPException(409, "A source with that name already exists") from exc
        finally:
            handle.close()
            temp.unlink(missing_ok=True)
    return {"filename": name}


def find_job(request: Request, job_id: str) -> Job:
    result = request.app.state.database.get(job_id)
    if result is None:
        raise HTTPException(404, "Job not found")
    return result


@router.post("/jobs", response_model=Job, status_code=202)
def create_job(data: JobRequest, request: Request) -> Job:
    settings = request.app.state.settings
    try:
        source_path(settings.root / "input", data.filename, settings.max_input_bytes)
        campaign = load_campaign(settings.root, data.campaign)
        resolved = resolve_request(data, campaign)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    job = request.app.state.database.create(resolved)
    request.app.state.worker.wake.set()
    return job


@router.get("/jobs", response_model=list[Job])
def list_jobs(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[Job]:
    return request.app.state.database.list(limit)


@router.get("/jobs/{job_id}", response_model=Job)
def job_status(job_id: str, request: Request) -> Job:
    return find_job(request, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str, request: Request) -> Job:
    job = request.app.state.database.cancel(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def clip_folder(request: Request, job: Job) -> Path:
    with request.app.state.database.transaction() as conn:
        if conn.execute("SELECT 1 FROM run_jobs WHERE job_id=?", (job.job_id,)).fetchone():
            raise HTTPException(403, "Open the studio to review and export a V2 clip")
    try:
        return child(request.app.state.settings.root / "output", job.job_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, "Job output directory is unavailable") from exc


def read_clips(folder: Path) -> list[Clip]:
    try:
        return CLIPS.validate_json(child(folder, "clips.json").read_bytes())
    except (ValueError, OSError) as exc:
        raise HTTPException(409, "Clip index is unavailable") from exc


def find_clip(clips: list[Clip], clip_id: str) -> tuple[int, Clip]:
    for index, clip in enumerate(clips):
        if clip.clip_id == clip_id:
            return index, clip
    raise HTTPException(404, "Verified clip not found")


@router.get("/jobs/{job_id}/clips", response_model=list[Clip])
def list_clips(job_id: str, request: Request) -> list[Clip]:
    job = find_job(request, job_id)
    return read_clips(clip_folder(request, job)) if job.status in READY else []


def artifact(folder: Path, filename: str, mime: str | None = None) -> FileResponse:
    try:
        path = child(folder, filename)
        if not path.is_file():
            raise FileNotFoundError
    except (ValueError, OSError) as exc:
        raise HTTPException(404, "File is unavailable") from exc
    return FileResponse(path, media_type=mime, filename=filename)


@router.get("/jobs/{job_id}/clips/{clip_id}/download")
def download(job_id: str, clip_id: str, request: Request) -> FileResponse:
    job = find_job(request, job_id)
    _, clip = find_clip(list_clips(job_id, request), clip_id)
    return artifact(clip_folder(request, job), clip.file, "video/mp4")


@router.get("/jobs/{job_id}/metadata.csv")
def metadata_table(job_id: str, request: Request) -> FileResponse:
    job = find_job(request, job_id)
    if job.status not in READY:
        raise HTTPException(409, "Job has no completed clip export")
    return artifact(clip_folder(request, job), "metadata.csv", "text/csv")


@router.get("/jobs/{job_id}/clips/{clip_id}/subtitle")
def subtitle(job_id: str, clip_id: str, request: Request) -> FileResponse:
    job = find_job(request, job_id)
    _, clip = find_clip(list_clips(job_id, request), clip_id)
    if not clip.subtitle_file:
        raise HTTPException(404, "Subtitles are unavailable")
    return artifact(clip_folder(request, job), clip.subtitle_file, "application/x-subrip")


def update_clip(job: Job, clip_id: str, request: Request, update: Review | Metadata) -> Clip:
    if job.status not in READY:
        raise HTTPException(409, "Job has no completed clip export")
    folder = clip_folder(request, job)
    try:
        with FileLock(str(folder / ".metadata.lock"), timeout=5):
            clips = read_clips(folder)
            index, clip = find_clip(clips, clip_id)
            if isinstance(update, Review):
                changes = {"review": update}
            else:
                campaign = load_campaign(request.app.state.settings.root, job.request.campaign)
                issues = metadata_issues(update, campaign)
                if issues:
                    raise HTTPException(422, "; ".join(issues))
                changes = update.model_dump()
                changes["review"] = Review(status="pending")
                if clip.hook_burned and changes["hook"] != clip.hook:
                    raise HTTPException(422, "The opening hook is burned in. Submit a new job to change it.")
            clips[index] = clip.model_copy(update=changes)
            export_metadata(folder, clips)
            return clips[index]
    except Timeout as exc:
        raise HTTPException(409, "Another metadata edit is in progress") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, "Could not update the local clip metadata") from exc


@router.put("/jobs/{job_id}/clips/{clip_id}/review", response_model=Clip)
def review_clip(job_id: str, clip_id: str, data: Review, request: Request) -> Clip:
    return update_clip(find_job(request, job_id), clip_id, request, data)


@router.put("/jobs/{job_id}/clips/{clip_id}/metadata", response_model=Clip)
def edit_metadata(job_id: str, clip_id: str, data: Metadata, request: Request) -> Clip:
    return update_clip(find_job(request, job_id), clip_id, request, data)
