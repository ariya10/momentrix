from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from threading import Event

import httpx
from fastapi.testclient import TestClient
import pytest

from app.database import Database
from app.main import create_app
from app.schemas import JobRequest, Status
from app.v2 import runs
from app.v2.storage import migrate, seed, uid
from app.workers.job_worker import Worker


def credentials(settings):
    return settings.model_copy(update={"service_token":"test-service-credential-123456789",
                                       "webhook_secret":"test-webhook-credential-123456789","api_token":"test-v1-workspace-credential-123456789"})


def client_for(settings):
    return TestClient(create_app(settings),base_url="http://localhost",client=("127.0.0.1",51000))


def login(client, settings):
    client.headers.update({"X-Momentrix-Client":"website"})
    token = (settings.root/"data"/"studio.key").read_text()
    assert client.post("/api/v2/session",json={"token":token}).status_code==200


def test_migration_keeps_all_legacy_payloads_and_backs_up_before_upgrade(settings):
    db = Database(settings.root/"data"/"jobs.sqlite3")
    db.initialize()
    job = db.create(JobRequest(filename="legacy.mp4"))
    migrate(db)
    backups = list((db.path.parent/"backups").glob("*.sqlite3"))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as old:
        assert old.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert old.execute("SELECT id FROM jobs").fetchone()[0]==job.job_id
        assert not old.execute("SELECT 1 FROM sqlite_master WHERE name='projects'").fetchone()
    seed(settings,db)
    migrate(db)
    seed(settings,db)
    with db.transaction() as c:
        assert c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]==1
        assert c.execute("PRAGMA foreign_key_check").fetchall()==[]
    assert db.get(job.job_id)==job
    assert list((db.path.parent/"backups").glob("*.sqlite3"))==backups


def test_sessions_require_separate_credentials_and_origin(settings):
    settings=credentials(settings)
    with client_for(settings) as client:
        v="/api/v2"
        assert client.get(v+"/projects").status_code==401
        assert client.get(v+"/projects",headers={"X-API-Token":settings.api_token}).status_code==401
        assert client.post(v+"/session",json={"token":settings.api_token}).status_code==403
        login(client,settings)
        assert client.get(v+"/session").json()=={"authenticated":True}
        assert client.post(v+"/projects",headers={"Origin":"https://foreign.example"},json={}).status_code==403
        assert client.post(v+"/projects",json={"name":"Example","authorized":False}).status_code==422
        assert client.get(v+"/internal/runs/missing").status_code==401
        assert client.get("/jobs").status_code==401
        assert client.get(v+"/internal/runs/missing",headers={"X-Momentrix-Service":settings.service_token}).status_code==404
        assert client.delete(v+"/session").is_success
        assert client.get(v+"/projects").status_code==401


def test_persisted_generation_replay_cancel_retry_and_dedup(settings,monkeypatch):
    settings=credentials(settings)
    entered,release=Event(),Event()
    def process(self,job):
        entered.set()
        release.wait(10)
        self.database.finish(job.job_id,Status.COMPLETED)
    def offline(*args):
        raise ValueError("Fixture simulates a disconnected n8n webhook")
    monkeypatch.setattr(runs,"dispatch_webhook",offline)
    monkeypatch.setattr(Worker,"process",process)
    with client_for(settings) as client:
        try:
            login(client,settings)
            p=client.post("/api/v2/projects",json={"name":"Audit","authorized":True}).json()["id"]
            a=uid()
            with client.app.state.database.transaction(write=True) as c:
                c.execute("INSERT INTO assets VALUES (?,?,?,?,?,?)",(a,p,"source.mp4","stored.mp4","digest","{}"))
            body={"asset_id":a,"idempotency_key":"event-key-001","options":{"count":1}}
            url=f"/api/v2/projects/{p}/generate"
            created=client.post(url,json=body)
            assert created.status_code==202
            r=created.json()["id"]
            retry_url=f"/api/v2/runs/{r}"
            assert client.get(retry_url).json()["status"]=="dispatch_failed"
            with client.app.state.database.transaction(write=True) as c:
                prior = c.execute("SELECT options FROM runs WHERE id=?", (r,)).fetchone()[0]
                doc = json.loads(prior)
                doc.pop("processing_preset")
                c.execute("UPDATE runs SET options=? WHERE id=?", (json.dumps(doc), r))
            assert client.post(url,json=body).json()["id"]==r
            assert client.post(url,json=body|{"options":{"count":1,"processing_preset":"quality"}}).status_code==409
            assert client.post(url,json=body|{"options":{"count":2}}).status_code==409
            assert client.post(retry_url+"/cancel").json()["status"]=="cancelled"
            callback={"run_id":r,"project_id":p,"asset_id":a,"idempotency_key":body["idempotency_key"],
                      "correlation_id":created.json()["correlation_id"],"execution_id":"fixture"}
            headers={"X-Momentrix-Service":settings.service_token}
            start=f"/api/v2/internal/runs/{r}/start"
            assert client.post(start,json=callback,headers=headers).status_code==409
            retry=client.post(retry_url+"/retry")
            assert retry.status_code==202
            assert client.post(start,json=callback,headers=headers).status_code==409
            callback["correlation_id"]=retry.json()["correlation_id"]
            def replay(_):
                return client.post(start,json=callback,headers=headers).status_code
            with ThreadPoolExecutor(2) as pool:
                assert list(pool.map(replay,[0,1]))==[200,200]
            assert entered.wait(2)
            with client.app.state.database.transaction() as c:
                assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]==1
                assert c.execute("SELECT COUNT(*) FROM run_jobs").fetchone()[0]==1
            assert len(client.get("/api/v2/projects").json())==1
        finally:
            release.set()


def test_campaign_validation_and_upload_reject_before_publication(settings):
    with client_for(settings) as client:
        login(client,settings)
        v="/api/v2"
        assert client.post(v+"/campaigns",json={"name":"Dates","category":"Test","date_start":"2026-01-10","date_end":"2026-01-01"}).status_code==422
        campaign=client.post(v+"/campaigns",json={"name":"Test rules","category":"Test","required_hashtags":["#Test"]}).json()
        assert client.patch(v+"/campaigns/"+campaign["id"],json={"archived":True}).json()["archived"]
        project=client.post(v+"/projects",json={"name":"Upload","authorized":True}).json()["id"]
        path=f"{v}/projects/{project}/assets"
        assert client.post(path,headers={"X-Filename":"../x.mp4"},content=b"x").status_code==422
        assert client.post(path,headers={"X-Filename":"x.mp4"},content=b"invalid").status_code==422
        assert list((settings.root/"input").iterdir())==[]
        assert client.get(f"{v}/projects/{project}").json()["assets"]==[]


def test_webhook_uses_expected_header_and_validates_202_receipt(settings,monkeypatch):
    settings=credentials(settings)
    payload={"run_id":uid()}
    original=httpx.Client
    receipt={"run_id":"wrong"}
    def handler(req):
        assert req.url.path=="/webhook/momentrix/v2/generate"
        assert req.headers["X-Momentrix-Webhook"]==settings.webhook_secret
        assert "X-Momentrix-Service" not in req.headers
        assert json.loads(req.content)==payload
        return httpx.Response(202,json=receipt)
    monkeypatch.setattr(httpx,"Client",lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(ValueError,match="receipt"):
        runs.dispatch_webhook(settings,"generate",payload)
    receipt.update(payload)
    runs.dispatch_webhook(settings,"generate",payload)


@pytest.mark.parametrize("webhook_code,body,verified", [
    (404, {"message": "not registered"}, False),
    (200, {"status": "unexpected"}, False),
    (200, {"status": "ok"}, True),
])
def test_connection_verifies_the_authenticated_production_webhook(settings, monkeypatch, webhook_code, body, verified):
    settings = credentials(settings)
    original = httpx.Client

    def n8n(request):
        if request.url.path == "/healthz":
            assert "X-Momentrix-Webhook" not in request.headers
            return httpx.Response(200, json={"status": "ok"})
        assert request.url.path == "/webhook/momentrix/v2/connection-test"
        assert request.headers["X-Momentrix-Webhook"] == settings.webhook_secret
        assert "X-Momentrix-Service" not in request.headers
        return httpx.Response(webhook_code, json=body)

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(n8n), **kw))
    with client_for(settings) as client:
        login(client, settings)
        result = client.post("/api/v2/system/test-n8n").json()
    assert result["reachable"] and result["configured"]
    assert result["verified"] is verified
    assert settings.webhook_secret not in result["detail"]


def test_scheduled_scan_is_allowlisted_queued_and_deduplicated(settings, monkeypatch):
    from time import monotonic, sleep
    from app.v2 import assets, media_assets

    settings = credentials(settings).model_copy(update={
        "scheduled_filenames": ["Allowed.mp4", "Missing.mp4"],
    })
    (settings.root/"input"/"Allowed.mp4").write_bytes(b"authorized sample")
    (settings.root/"input"/"Outside.mp4").write_bytes(b"other sample")
    monkeypatch.setattr(assets, "inspect_source", lambda *args: {"duration":35,"width":640,"height":360})
    monkeypatch.setattr(media_assets, "prepare_asset", lambda *args: {})

    def wait_for_scan(client):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            batch = client.get("/api/v2/automation/ingestion").json()
            if batch["status"] == "completed":
                return batch
            sleep(0.05)
        raise AssertionError("Scheduled ingestion did not complete")

    with client_for(settings) as client:
        login(client, settings)
        route = "/api/v2/internal/ingestion/scan"
        assert client.post(route).status_code == 401
        headers = {"X-Momentrix-Service":settings.service_token}
        assert client.post(route, headers=headers).status_code == 202
        first = wait_for_scan(client)
        assert len(first["imported"]) == 1 and first["duplicates"] == 0
        assert len(first["errors"]) == 1 and "Missing.mp4" in first["errors"][0]
        assert client.post(route, headers=headers).status_code == 202
        second = wait_for_scan(client)
        assert second["imported"] == [] and second["duplicates"] == 1
        projects = client.get("/api/v2/projects").json()
        assert [p["name"] for p in projects] == ["Allowed"]
        assert projects[0]["runs"] == []
        health = client.post("/api/v2/internal/maintenance", headers=headers).json()
        assert health["free_disk_bytes"] > 0 and health["queued_jobs"] == 0

