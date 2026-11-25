import json
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.database import Database
from app.main import create_app
from app.schemas import Clip, FacecamDetection, JobRequest, Region, Status
from app.services import audio, clip_selector, facecam, video_editor
from app.services.chunking import Chunk
from app.services.metadata import export_metadata
from app.workers import job_worker
from app.workers.job_worker import Worker


def local_client(settings):
    return TestClient(create_app(settings), base_url="http://localhost", client=("127.0.0.1", 50000))


def wait_for(client, job_id, state):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] == state:
            return job
        sleep(0.05)
    raise AssertionError(f"Expected {state}, observed {job['status']}")


def test_job_recovery_and_cancellation(settings):
    database = Database(settings.root / "data" / "jobs.sqlite3")
    database.initialize()
    task = JobRequest(filename="a.mp4")
    first, second, third = [database.create(task) for _ in range(3)]
    assert database.claim().job_id == first.job_id
    assert database.claim().job_id == second.job_id
    database.advance(first.job_id, Status.TRANSCRIBING, 30)
    database.cancel(second.job_id)
    database.recover_interrupted()
    assert database.get(first.job_id).status == Status.FAILED
    assert database.get(first.job_id).error.startswith("Backend stopped")
    assert database.get(second.job_id).status == Status.CANCELLED
    assert database.get(third.job_id).status == Status.QUEUED
    assert database.cancel(third.job_id).status == Status.CANCELLED
    assert database.claim() is None


def test_api_validates_and_cancels_without_blocking(settings, monkeypatch):
    block = Event()

    def process(self, job):
        block.wait(6)
        self.database.finish(job.job_id, Status.COMPLETED)

    monkeypatch.setattr(Worker, "process", process)
    with local_client(settings) as client:
        try:
            assert client.get("/health").json() == {"status": "ok"}
            assert client.get("/campaigns").json()[0]["id"] == "default"
            headers = {"X-Filename": "Test%20%C3%A9.webm"}
            assert client.post("/sources", content=b"media", headers=headers).status_code == 201
            assert client.post("/sources", content=b"no overwrite", headers=headers).status_code == 409
            assert client.get("/sources").json() == ["Test é.webm"]
            assert client.post("/jobs", json={"filename": "../outside.mp4", "authorized": True}).status_code == 400
            assert client.post("/jobs", json={"filename": "Test é.webm"}).status_code == 400
            created = client.post("/jobs", json={"filename": "Test é.webm", "authorized": True})
            assert created.status_code == 202
            job_id = created.json()["job_id"]
            assert client.get("/jobs").json()[0]["job_id"] == job_id
            wait_for(client, job_id, "probing")
            assert client.post(f"/jobs/{job_id}/cancel").json()["cancel_requested"] is True
            block.set()
            assert wait_for(client, job_id, "cancelled")["finished_at"]
            assert client.get(f"/jobs/{job_id}/clips").json() == []
            assert client.get(f"/jobs/{job_id}/clips/clip_01/download").status_code == 404
            assert client.get("/jobs/missing").status_code == 404
        finally:
            block.set()


def test_api_access_token(settings):
    secure = settings.model_copy(update={"api_token": "local-only-testing-token-value"})
    with local_client(secure) as client:
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers={"x-api-token": "wrong"}).status_code == 401
        assert client.get("/health", headers={"x-api-token": secure.api_token}).status_code == 200


def test_nonlocal_clients_cannot_spoof_loopback_host(settings):
    with TestClient(create_app(settings), base_url="http://localhost", client=("192.0.2.10", 50000)) as client:
        assert client.get("/health").status_code == 403


def test_job_reports_the_exact_failed_campaign_rule(settings, monkeypatch, transcript, clip_candidate):
    media = audio.Media(120, 640, 360, 30, "h264", "yuv420p", "1:1", 0, 0, (1,), ("aac",))
    candidate = clip_candidate.model_copy(update={"hashtags": ["#KAICENAT"]})
    monkeypatch.setattr(audio, "probe", lambda *_: media)
    monkeypatch.setattr(job_worker, "cached_transcript", lambda *_: transcript)
    monkeypatch.setattr(clip_selector, "select", lambda *_: [(candidate, Chunk(0, 30, ()))])
    (settings.root / "input" / "sample.mp4").write_bytes(b"source")

    with local_client(settings) as client:
        response = client.post("/jobs", json={
            "filename": "sample.mp4", "campaign": "kai_cenat", "authorized": True, "count": 1,
        })
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        job = wait_for(client, job_id, "completed_with_warnings")
        assert "Missing hook reference to Kai Cenat in 1 candidate." in job["warnings"]
        assert client.get(f"/jobs/{job_id}/clips").json() == []
        report_path = settings.root / job["output"] / "job_report.json"
        report = json.loads(report_path.read_bytes())
        assert report["campaign_rejections"] == {"Missing hook reference to Kai Cenat": 1}
        assert report["rejected_candidates"] == {"campaign requirements": 1}


@pytest.mark.parametrize("detected", [True, False])
def test_automatic_facecam_jobs_publish_effective_layout(settings, monkeypatch, transcript, clip_candidate, detected):
    region = Region(x=480, y=10, width=130, height=120) if detected else None
    detection = FacecamDetection(region=region, sampled_frames=7, matching_frames=5 if detected else 0)
    media = audio.Media(120, 640, 360, 30, "h264", "yuv420p", "1:1", 0, 0, (1,), ("aac",))
    monkeypatch.setattr(audio, "probe", lambda *_: media)
    monkeypatch.setattr(job_worker, "cached_transcript", lambda *_: transcript)
    monkeypatch.setattr(clip_selector, "select", lambda *_: [(clip_candidate, Chunk(0, 30, ()))])
    monkeypatch.setattr(facecam, "detect", lambda *_: detection)
    expected_layout = "split" if detected else "fit"

    def render(settings, source, target, media, candidate, request, ass, cancel):
        assert request.layout == expected_layout
        if detected:
            assert request.facecam == region
            assert request.gameplay == Region(x=0, y=0, width=640, height=360)
        target.write_bytes(b"video")

    monkeypatch.setattr(video_editor, "render", render)
    monkeypatch.setattr(job_worker, "quality_check", lambda *_: ["verified"])
    (settings.root / "input" / "sample.mp4").write_bytes(b"source")
    with local_client(settings) as client:
        created = client.post("/jobs", json={
            "filename": "sample.mp4", "authorized": True, "layout": "auto_split", "count": 1,
        })
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        expected_status = "completed" if detected else "completed_with_warnings"
        job = wait_for(client, job_id, expected_status)
        assert any("Used Fit layout" in warning for warning in job["warnings"]) == (not detected)
        clip, = client.get(f"/jobs/{job_id}/clips").json()
        assert clip["render_layout"] == expected_layout
        assert clip["facecam_detection"] == detection.model_dump()


def test_verified_clips_support_download_and_review(settings, monkeypatch, clip_candidate):
    def process(self, job):
        folder = self.settings.root / "output" / job.job_id
        folder.mkdir()
        (folder / "clip_01.mp4").write_bytes(b"stub")
        clip = Clip(**clip_candidate.model_dump(), clip_id="clip_01", file="clip_01.mp4", duration=30,
                    technical_checks=["stub"], manual_review=["Review visuals"])
        export_metadata(folder, [clip])
        self.database.finish(job.job_id, Status.COMPLETED)

    monkeypatch.setattr(Worker, "process", process)
    (settings.root / "input" / "a.mp4").write_bytes(b"source")
    with local_client(settings) as client:
        job_id = client.post("/jobs", json={"filename": "a.mp4", "authorized": True}).json()["job_id"]
        wait_for(client, job_id, "completed")
        path = f"/jobs/{job_id}/clips/clip_01"
        assert client.get(f"{path}/download").content == b"stub"
        assert client.put(f"{path}/review", json={"status": "approved"}).json()["review"]["status"] == "approved"
        keys = {"hook", "title", "caption", "description", "hashtags"}
        updated = {**clip_candidate.model_dump(include=keys), "title": "Updated local title"}
        result = client.put(f"{path}/metadata", json=updated).json()
        assert result["title"] == updated["title"] and result["review"]["status"] == "pending"
        assert updated["title"] in client.get(f"/jobs/{job_id}/metadata.csv").text
