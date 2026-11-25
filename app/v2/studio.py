from collections import Counter
from datetime import date
import logging
import re
import json
from pathlib import Path
import shutil
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
import httpx
from pydantic import Field, ValidationError, model_validator

from app.api.routes import sources as local_sources, system_status
from app.schemas import Campaign, ProcessingPreset, ShortText, StrictModel
from app.v2 import assets
from app.v2.ingestion import queue_scan, scan_view
from app.v2.runs import run_info
from app.v2.security import internal_configured
from app.v2.storage import now, sync_legacy, uid

router = APIRouter()
Content = Literal["gaming","livestream","podcast","interview","reaction","educational","general"]


class NewProject(StrictModel):
    name: ShortText
    content_type: Content = "general"
    authorized: Literal[True]


class ProjectEdit(StrictModel):
    name: ShortText | None = None
    content_type: Content | None = None


class Preset(Campaign):
    archived: bool = False
    platform: str = Field(default="",max_length=100)
    date_start: date | None = None
    date_end: date | None = None

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.date_start and self.date_end and self.date_end<self.date_start:
            raise ValueError("Campaign end date precedes start date")
        return self


class CreatePreset(Preset):
    id: str | None = Field(default=None,pattern=r"^[a-z0-9_]{1,48}$")


def project(c,row,settings):
    if not row:
        raise HTTPException(404,"Project not found")
    result = dict(row)
    result["legacy"] = bool(row["legacy"])
    result["assets"] = [assets.present_asset(a) for a in c.execute("SELECT * FROM assets WHERE project_id=?",(row["id"],))]
    result["runs"] = [run_info(c,r,settings) for r in c.execute(
        "SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC",(row["id"],))]
    return result


@router.post("/projects",status_code=201)
def create_project(data:NewProject,request:Request):
    db = request.app.state.database
    with db.transaction(write=True) as c:
        key = uid()
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,0)",(key,data.name,data.content_type,1,now()))
        return project(c,c.execute("SELECT * FROM projects WHERE id=?",(key,)).fetchone(),request.app.state.settings)


@router.get("/projects")
def projects(request:Request):
    db = request.app.state.database
    sync_legacy(db)
    with db.transaction() as c:
        return [project(c,r,request.app.state.settings) for r in c.execute("SELECT * FROM projects ORDER BY created_at DESC")]


@router.get("/projects/{project_id}")
def get_project(project_id:str,request:Request):
    with request.app.state.database.transaction() as c:
        return project(c,c.execute("SELECT * FROM projects WHERE id=?",(project_id,)).fetchone(),request.app.state.settings)


@router.patch("/projects/{project_id}")
def edit_project(project_id:str,data:ProjectEdit,request:Request):
    with request.app.state.database.transaction(write=True) as c:
        c.execute("UPDATE projects SET name=COALESCE(?,name),content_type=COALESCE(?,content_type) WHERE id=?",
                  (data.name,data.content_type,project_id))
    return get_project(project_id,request)


@router.get("/sources")
def sources(request:Request):
    return [name for name in local_sources(request) if not name.startswith("mx-")]


@router.post("/projects/{project_id}/assets",status_code=201)
async def add_asset(project_id:str,request:Request,processing_preset: ProcessingPreset = "balanced"):
    result = await assets.ingest(request,project_id,processing_preset)
    request.app.state.worker.wake.set()
    return result


@router.get("/assets/{asset_id}")
def get_asset(asset_id:str,request:Request):
    return assets.present_asset(assets.asset_record(request.app.state.database,asset_id))


@router.get("/assets/{asset_id}/preview")
def preview(asset_id:str,request:Request):
    from app.v2.media_assets import preview_path
    path = preview_path(request.app.state.settings,assets.asset_record(request.app.state.database,asset_id))
    return FileResponse(path)


@router.get("/assets/{asset_id}/thumbnail")
def thumbnail(asset_id:str,request:Request,index:int=Query(default=0,ge=0,le=1000)):
    from app.v2.media_assets import thumbnail_path
    path = thumbnail_path(request.app.state.settings,assets.asset_record(request.app.state.database,asset_id),index)
    return FileResponse(path)


@router.get("/assets/{asset_id}/timeline")
def timeline(asset_id:str,request:Request):
    from app.v2.media_assets import timeline as read_timeline
    return read_timeline(request.app.state.settings,assets.asset_record(request.app.state.database,asset_id))


@router.get("/campaigns")
def campaigns(request:Request):
    with request.app.state.database.transaction() as c:
        return [dict(id=r[0],**json.loads(r[1])) for r in c.execute("SELECT * FROM campaign_presets ORDER BY id")]


@router.post("/campaigns",status_code=201)
def new_campaign(data:CreatePreset,request:Request):
    key = data.id or uid()
    doc = data.model_dump(mode="json",exclude={"id"})
    with request.app.state.database.transaction(write=True) as c:
        if c.execute("SELECT 1 FROM campaign_presets WHERE id=?",(key,)).fetchone():
            raise HTTPException(409,"Campaign ID already exists")
        c.execute("INSERT INTO campaign_presets VALUES (?,?)",(key,json.dumps(doc)))
    return dict(id=key,**doc)


@router.patch("/campaigns/{campaign_id}")
def patch_campaign(campaign_id:str,data:dict,request:Request):
    with request.app.state.database.transaction(write=True) as c:
        row = c.execute("SELECT document FROM campaign_presets WHERE id=?",(campaign_id,)).fetchone()
        if not row:
            raise HTTPException(404,"Campaign not found")
        try:
            doc = Preset.model_validate(json.loads(row[0]) | data)
        except ValidationError as exc:
            raise HTTPException(422,str(exc)) from exc
        c.execute("UPDATE campaign_presets SET document=? WHERE id=?",(doc.model_dump_json(),campaign_id))
    return dict(id=campaign_id,**doc.model_dump(mode="json"))


@router.get("/system/status")
def status(request:Request):
    settings = request.app.state.settings
    return dict(**system_status(request).model_dump(),n8n_configured=internal_configured(settings),
                cpu_threads=settings.cpu_threads,max_input_bytes=settings.max_input_bytes)


@router.post("/system/test-n8n")
def test_connection(request:Request):
    settings = request.app.state.settings
    configured = internal_configured(settings)
    result = {"reachable": False, "configured": configured, "verified": False}
    try:
        with httpx.Client(base_url=str(settings.n8n_url), trust_env=False, timeout=6) as client:
            result["reachable"] = client.get("healthz").is_success
            if not result["reachable"]:
                return dict(result, detail="n8n health check failed.")
            if not configured:
                return dict(result, detail="n8n is reachable. Configure the webhook and service credentials to test the connection.")
            response = client.get("webhook/momentrix/v2/connection-test",
                                  headers={"X-Momentrix-Webhook": settings.webhook_secret})
    except httpx.HTTPError:
        detail = "The n8n connection webhook timed out or could not be reached." if result["reachable"] else "n8n health check failed."
        return dict(result, detail=detail)
    if not response.is_success:
        return dict(result, detail=f"n8n is reachable. The production connection test returned HTTP {response.status_code}.")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("status") != "ok":
        return dict(result, detail="The production connection test returned an unexpected response.")
    return dict(result, verified=True, detail="The authenticated production webhook reached FastAPI.")


@router.get("/system/metrics")
def metrics(request:Request):
    from app.v2.clips import list_catalog
    db,settings = request.app.state.database,request.app.state.settings
    all_projects = projects(request)
    clips = list_catalog(settings,db)
    runs = [r for p in all_projects for r in p["runs"]]
    completed = {"completed","completed_with_warnings","awaiting_review"}
    stages, distribution, rejected = Counter(),Counter(),Counter()
    source_seconds = 0.0
    times = []
    with db.transaction() as c:
        for row in c.execute("SELECT job_id FROM runs WHERE job_id IS NOT NULL"):
            path = settings.root/"output"/row[0]/"job_report.json"
            if path.is_file():
                report = json.loads(path.read_bytes())
                source_seconds += report.get("source_duration",0)
                if "elapsed_seconds" in report:
                    times.append(report["elapsed_seconds"])
                stages.update(report.get("stage_seconds",{}))
    for clip in clips:
        distribution[min(9,clip["score"]//10)*10] += 1
        if clip["review"]["status"]=="rejected":
            rejected[clip["category"]] += 1
    finished = [r for r in runs if r["status"] in completed|{"failed","cancelled"}]
    return dict(total_projects=len(all_projects),completed_projects=sum(any(r["status"] in completed for r in p["runs"]) for p in all_projects),
                processing_jobs=sum(r["status"] not in completed|{"cancelled","failed","dispatch_failed","awaiting_automation"} for r in runs),
                failed_jobs=sum(r["status"]=="failed" for r in runs),total_clips=len(clips),approved_clips=sum(c["review"]["status"]=="approved" for c in clips),
                rejected_clips=sum(rejected.values()),exported_clips=sum(c["exported"] for c in clips),source_seconds=source_seconds,
                failure_rate=sum(r["status"]=="failed" for r in finished)/len(finished) if finished else None,
                average_processing_seconds=sum(times)/len(times) if times else None,stage_seconds=stages,
                rejected_categories=rejected,score_distribution=[{"score":f"{s}–{100 if s==90 else s+9}","count":n} for s,n in sorted(distribution.items())])


class Diagnostic(StrictModel):
    execution_id: str | None = Field(default=None,max_length=100)
    workflow_name: str = Field(max_length=200)
    node: str = Field(max_length=200)
    run_id: str | None = Field(default=None,max_length=100)
    summary: str = Field(min_length=1,max_length=2000)


@router.post("/internal/automation/errors")
def record_error(data:Diagnostic,request:Request):
    with request.app.state.database.transaction(write=True) as c:
        row = c.execute("SELECT id FROM runs WHERE id=? OR execution_id=? LIMIT 1",(data.run_id,data.execution_id)).fetchone()
        key = row[0] if row else None
        c.execute("""INSERT INTO automation_errors(execution_id,workflow_name,node,run_id,summary,at)
                     VALUES (?,?,?,?,?,?)""",(data.execution_id,data.workflow_name,data.node,key,data.summary,now()))
    return {"recorded":True,"run_id":key}


@router.get("/automation/errors")
def errors(request:Request):
    with request.app.state.database.transaction() as c:
        return [dict(row) for row in c.execute("SELECT seq AS id,summary AS detail,at AS created_at,* FROM automation_errors ORDER BY seq DESC LIMIT 200")]


@router.post("/internal/maintenance")
def maintenance(request:Request):
    settings,db = request.app.state.settings,request.app.state.database
    with db.transaction() as c:
        interrupted = c.execute("SELECT COUNT(*) FROM jobs WHERE status='failed' AND instr(payload,'Backend stopped')>0").fetchone()[0]
        queued = c.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
        pending_tasks = c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','working')").fetchone()[0]
    cache_sizes = []
    for path in (settings.root/"cache").glob("*.json"):
        if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name) or path.is_symlink():
            continue
        try:
            cache_sizes.append(path.stat().st_size)
        except FileNotFoundError:
            continue
    result = dict(at=now(),free_disk_bytes=shutil.disk_usage(settings.root).free,interrupted_jobs=interrupted,
                  queued_jobs=queued, pending_tasks=pending_tasks,
                  cached_transcripts=len(cache_sizes),cache_json_bytes=sum(cache_sizes))
    logging.getLogger("momentrix.maintenance").info("storage_health free_bytes=%s interrupted=%s",result["free_disk_bytes"],interrupted)
    return result


@router.post("/internal/ingestion/scan", status_code=202)
def scan(request: Request):
    state = request.app.state
    receipt = queue_scan(state.database, state.settings)
    state.worker.wake.set()
    return receipt


@router.get("/automation/ingestion")
def scan_status(request: Request):
    with request.app.state.database.transaction() as conn:
        latest = conn.execute("SELECT * FROM tasks WHERE kind='ingest_scan' ORDER BY created_at DESC LIMIT 1").fetchone()
    return scan_view(latest) if latest is not None else None

