import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, ValidationError

from app.schemas import Campaign, Job, JobRequest, Status, StrictModel, TERMINAL
from app.services.campaigns import resolve_request
from app.v2.security import authenticated, internal_configured
from app.v2.storage import now, uid

router = APIRouter()
Identifier = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")]


class Generation(StrictModel):
    asset_id: Identifier
    idempotency_key: Key
    options: dict = Field(default_factory=dict)


class Start(StrictModel):
    run_id: Identifier
    project_id: Identifier
    asset_id: Identifier
    correlation_id: Identifier
    idempotency_key: Key
    execution_id: str | None = Field(default=None,max_length=100)


def dispatch_webhook(settings, action, payload):
    if not internal_configured(settings):
        raise ValueError("Configure distinct local n8n webhook and service credentials before dispatch.")
    url = f"{str(settings.n8n_url).rstrip('/')}/webhook/momentrix/v2/{action}"
    try:
        with httpx.Client(trust_env=False,timeout=12) as client:
            response = client.post(url,headers={"X-Momentrix-Webhook":settings.webhook_secret},json=payload)
        if response.status_code != 202:
            raise ValueError(f"n8n webhook returned HTTP {response.status_code}. Check workflow activation and credentials.")
        key = "run_id" if action=="generate" else "export_id"
        if response.json().get(key) != payload[key]:
            raise ValueError("The n8n receipt did not match the persisted request.")
    except httpx.HTTPError as exc:
        raise ValueError("Could not reach the configured local n8n webhook.") from exc


def run_info(c,row,settings):
    if not row:
        raise HTTPException(404,"Run not found")
    job = None
    if row["job_id"]:
        payload = c.execute("SELECT payload FROM jobs WHERE id=?",(row["job_id"],)).fetchone()
        if payload:
            job = Job.model_validate_json(payload[0])
    info = {k:row[k] for k in ("id","project_id","asset_id","correlation_id","created_at","error","execution_id","status")}
    info["processing_preset"] = json.loads(row["options"]).get("processing_preset")
    report = {}
    if job:
        path = settings.root/"output"/job.job_id/"job_report.json"
        if path.is_file():
            report = json.loads(path.read_bytes())
        status = job.status.value
        if row["status"]!="legacy" and status in {"completed","completed_with_warnings"} and report.get("exported_clips",0):
            status = "awaiting_review"
        info.update(status=status,stage=status,started_at=job.started_at,finished_at=job.finished_at,
                    updated_at=job.updated_at,error=job.error,warnings=job.warnings,
                    candidate_count=report.get("candidate_count"),rendered_count=report.get("exported_clips"))
    else:
        info.update(stage=row["status"],warnings=[])
    stages = c.execute("SELECT stage,at FROM run_events WHERE run_id=? ORDER BY seq",(row["id"],)).fetchall()
    info["completed_stages"] = list(dict.fromkeys(s[0] for s in stages if s[0] != info["stage"]))
    if stages:
        info.setdefault("updated_at",stages[-1][1])
    return info


def dispatch(settings, db, run_id):
    with db.transaction(write=True) as c:
        row = c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row or row["status"]!="awaiting_automation" or row["job_id"]:
            return
        payload = {k:row[k] for k in ("project_id","asset_id","correlation_id","idempotency_key")}
        payload["run_id"] = run_id
    try:
        dispatch_webhook(settings,"generate",payload)
    except ValueError as exc:
        with db.transaction(write=True) as c:
            c.execute("""UPDATE runs SET status='dispatch_failed',error=? WHERE id=?
                         AND job_id IS NULL AND status='awaiting_automation'""",(str(exc),run_id))


def create_run(settings,db,project_id,data):
    with db.transaction(write=True) as c:
        asset = c.execute("""SELECT a.*,p.authorized,p.legacy FROM assets a JOIN projects p ON p.id=a.project_id
                          WHERE a.id=? AND p.id=?""",(data.asset_id,project_id)).fetchone()
        if not asset or asset["legacy"] or not asset["authorized"]:
            raise HTTPException(422,"Choose an asset owned by an authorized V2 project")
        if {"filename","authorized"} & data.options.keys():
            raise HTTPException(422,"The project controls the source and authorization")
        try:
            options = JobRequest(**data.options,filename=asset["stored_name"],authorized=True)
            prior = c.execute("SELECT * FROM runs WHERE project_id=? AND idempotency_key=?",
                              (project_id,data.idempotency_key)).fetchone()
            if prior:
                if prior["asset_id"]!=data.asset_id or JobRequest.model_validate_json(prior["options"])!=options:
                    raise HTTPException(409,"This idempotency key was used with different settings")
                return prior["id"],False
            row = c.execute("SELECT document FROM campaign_presets WHERE id=?",(options.campaign,)).fetchone()
            if not row:
                raise ValueError("Unknown campaign")
            document = json.loads(row[0])
            if document.get("archived"):
                raise ValueError("The campaign is archived")
            today = datetime.now().date().isoformat()
            if (document.get("date_start") or today)>today or (document.get("date_end") or today)<today:
                raise ValueError("Outside the configured campaign dates")
            campaign = Campaign(**{k:v for k,v in document.items() if k in Campaign.model_fields})
            resolve_request(options,campaign)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        key = uid()
        c.execute("""INSERT INTO runs(id,project_id,asset_id,correlation_id,idempotency_key,status,created_at,
                  options,campaign,attempts) VALUES (?,?,?,?,?,'awaiting_automation',?,?,?,1)""",
                  (key,project_id,data.asset_id,uid(),data.idempotency_key,now(),options.model_dump_json(),
                   campaign.model_dump_json()))
        c.execute("INSERT INTO run_events(run_id,stage,at) VALUES (?,'awaiting_automation',?)",(key,now()))
    return key,True


@router.post("/projects/{project_id}/generate",status_code=202)
def generate(project_id:str,data:Generation,request:Request,background:BackgroundTasks):
    settings,db = request.app.state.settings,request.app.state.database
    key,fresh = create_run(settings,db,project_id,data)
    if fresh:
        background.add_task(dispatch,settings,db,key)
    return get_run(key,request)


@router.post("/internal/runs/{run_id}/start")
def start(run_id:str,data:Start,request:Request):
    db = request.app.state.database
    with db.transaction(write=True) as c:
        row = c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row or data.run_id!=run_id or any(getattr(data,k)!=row[k] for k in
                ("project_id","asset_id","correlation_id","idempotency_key")):
            raise HTTPException(409,"The callback does not match the persisted run")
        if row["status"]=="cancelled":
            raise HTTPException(409,"Run was cancelled")
        if not row["job_id"]:
            opts = resolve_request(JobRequest.model_validate_json(row["options"]),Campaign.model_validate_json(row["campaign"]))
            stamp = datetime.now(UTC)
            job = Job(job_id=uid(),request=opts,status=Status.QUEUED,progress=0,created_at=stamp,updated_at=stamp)
            c.execute("INSERT INTO jobs VALUES (?,?,?,?)",(job.job_id,job.status,stamp.isoformat(),job.model_dump_json()))
            c.execute("INSERT INTO run_jobs VALUES (?,?)",(job.job_id,run_id))
            c.execute("UPDATE runs SET job_id=?,status='queued',error=NULL,execution_id=? WHERE id=?",
                      (job.job_id,data.execution_id,run_id))
            c.execute("INSERT INTO run_events(run_id,stage,at) VALUES (?,'queued',?)",(run_id,now()))
    request.app.state.worker.wake.set()
    return get_run(run_id,request)


@router.get("/internal/runs/{run_id}")
@router.get("/runs/{run_id}")
def get_run(run_id:str,request:Request):
    with request.app.state.database.transaction() as c:
        return run_info(c,c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone(),request.app.state.settings)


@router.get("/runs")
def list_runs(request:Request):
    with request.app.state.database.transaction() as c:
        return [run_info(c,row,request.app.state.settings) for row in c.execute("SELECT * FROM runs ORDER BY created_at DESC")]


@router.post("/runs/{run_id}/cancel")
def cancel(run_id:str,request:Request):
    db = request.app.state.database
    with db.transaction(write=True) as c:
        row = c.execute("SELECT job_id FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row:
            raise HTTPException(404,"Run not found")
        if not row[0]:
            c.execute("UPDATE runs SET status='cancelled',error=NULL WHERE id=?",(run_id,))
            c.execute("INSERT INTO run_events(run_id,stage,at) VALUES (?,'cancelled',?)",(run_id,now()))
    if row[0]:
        db.cancel(row[0])
    return get_run(run_id,request)


@router.post("/runs/{run_id}/retry",status_code=202)
def retry(run_id:str,request:Request,background:BackgroundTasks):
    settings,db = request.app.state.settings,request.app.state.database
    with db.transaction(write=True) as c:
        row = c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
        info = run_info(c,row,settings)
        if row["status"]=="legacy" or info["status"] not in {"failed","cancelled","dispatch_failed","awaiting_automation"}:
            raise HTTPException(409,"This run cannot be retried in its current state")
        if row["attempts"]>=3:
            raise HTTPException(409,"Retry limit reached")
        c.execute("""UPDATE runs SET job_id=NULL,status='awaiting_automation',execution_id=NULL,error=NULL,
                     correlation_id=?,attempts=attempts+1 WHERE id=?""",(uid(),run_id))
        c.execute("INSERT INTO run_events(run_id,stage,at) VALUES (?,'awaiting_automation',?)",(run_id,now()))
    background.add_task(dispatch,settings,db,run_id)
    return get_run(run_id,request)


@router.get("/runs/{run_id}/events")
async def events(run_id:str,request:Request):
    get_run(run_id,request)
    async def stream():
        prior = None
        while not await request.is_disconnected() and authenticated(request):
            info = await asyncio.to_thread(get_run,run_id,request)
            data = json.dumps(info,default=str)
            if data!=prior:
                yield f"event: run\ndata: {data}\n\n"
                prior = data
            else:
                yield ": heartbeat\n\n"
            if info["status"] in {*TERMINAL,"awaiting_review","dispatch_failed"}:
                break
            await asyncio.sleep(2)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})

