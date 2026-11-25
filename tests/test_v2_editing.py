import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import Segment, Transcript, Word
from app.services.audio import Media
from app.utils.process import Cancelled, run
from app.v2.editing import EditDecision, NormalizedRegion, _write_captions, caption_timeline, render_revision


def timed_transcript():
    return Transcript(source_filename="stripes.mp4", source_duration=4, language="en",
                      segments=[Segment(start=0.3, end=3.2, text="One middle three four.", words=[
                          Word(start=0.3, end=0.8, text="One"),
                          Word(start=1.3, end=1.6, text="middle"),
                          Word(start=2.3, end=2.6, text="three"),
                          Word(start=2.8, end=3.2, text="four."),
                      ])])


def test_trim_jump_and_corrected_captions_keep_source_clock(tmp_path):
    edit = EditDecision(start_seconds=0.2, end_seconds=3.7, cuts=[{"start": 1, "end": 2}],
                        subtitle_style="karaoke", hook="A {\\k999} test")
    phrases = caption_timeline(edit, timed_transcript())
    assert [p.text for p in phrases] == ["One", "three four."]
    assert [p.start for p in phrases] == pytest.approx([0.1, 1.1], abs=1e-8)
    assert [p.end for p in phrases] == pytest.approx([0.6, 2.0], abs=1e-8)
    assert _write_captions(tmp_path, edit, timed_transcript())
    ass = (tmp_path / "captions.ass").read_text(encoding="utf-8")
    assert r"{\kf30}three{\k20} {\kf40}four." in ass
    assert "middle" not in ass
    assert r"{\k999}" not in ass
    assert "00:00:01.100 --> 00:00:02.000" in (tmp_path / "captions.vtt").read_text(encoding="utf-8")
    manual = EditDecision(**{**edit.model_dump(), "captions": [{"start": 0.8, "end": 2.2, "text": "Correction"}]})
    fixed = caption_timeline(manual, timed_transcript())
    assert [p.text for p in fixed] == ["Correction", "Correction"]
    assert [p.start for p in fixed] == pytest.approx([0.6, 0.8])
    assert [p.end for p in fixed] == pytest.approx([0.8, 1.0])
    assert not any(p.words for p in fixed)


@pytest.mark.parametrize("changes", [
    {"end_seconds": 0}, {"cuts": [{"start": 1, "end": 3}, {"start": 2, "end": 3.5}]},
    {"cuts": [{"start": 0, "end": 4}]}, {"layout": "roi"},
    {"layout": "pip", "facecam": {"x": 0.5, "y": 0.5, "width": 1, "height": 0.5}},
    {"subtitle_font": "Arial,Injected"}, {"subtitle_color": "red"},
    {"captions": [{"start": 1, "end": 2, "text": "a"}, {"start": 1.4, "end": 3, "text": "b"}]},
])
def test_invalid_decisions_fail_before_render(changes):
    with pytest.raises(ValidationError):
        EditDecision(**{"start_seconds": 0, "end_seconds": 4, **changes})


def test_normalized_crop_maps_to_decoded_source():
    media = Media(4, 640, 360, 30, "h264", "yuv420p", "1:1", 90, 0, (), ())
    roi = NormalizedRegion(x=0.5, y=0.1, width=0.5, height=0.5)
    assert roi.pixels(media).model_dump() == {"x": 320, "y": 36, "width": 320, "height": 180}
    with pytest.raises(ValueError, match="two pixels"):
        NormalizedRegion(x=0, y=0, width=0.0001, height=0.001).pixels(media)


@pytest.fixture
def render_setup(settings):
    installed = Settings()
    ffmpeg, ffprobe = installed.executable("ffmpeg"), installed.executable("ffprobe")
    if not shutil.which(ffmpeg) or not shutil.which(ffprobe):
        pytest.skip("FFmpeg and FFprobe are unavailable")
    cfg = settings.model_copy(update={"ffmpeg": ffmpeg, "ffprobe": ffprobe, "cpu_threads": 2})
    source = cfg.root / "input" / "stripes.mp4"
    run([ffmpeg, "-v", "error", "-n", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30",
         "-f", "lavfi", "-i", "aevalsrc='0.24*sin(2*PI*(if(lt(t,1),220,if(lt(t,2),440,880)))*t)':s=48000",
         "-t", "4", "-c:v", "libx264", "-c:a", "aac", str(source)], cwd=source.parent)
    return cfg, source


@pytest.mark.integration
def test_real_revision_reuses_exact_artifacts_and_remaps_audio(render_setup):
    settings, source = render_setup
    transcript = timed_transcript()
    edit = EditDecision(start_seconds=0.2, end_seconds=3.7, cuts=[{"start": 1, "end": 2}],
                        layout="blur", subtitle_style="karaoke", hook="A bridge?", normalize_audio=True)
    dest = settings.root / "output" / "edits" / "preview-1"
    target = render_revision(settings, source, transcript, edit, dest, preview=True)
    assert render_revision(settings, source, transcript, edit, dest, preview=True) == target
    info = json.loads((dest / "report.json").read_text(encoding="utf-8"))
    assert info["duration"] == pytest.approx(2.5, abs=1/30)
    assert (info["width"], info["height"]) == (360, 640)
    with pytest.raises(FileExistsError, match="different"):
        render_revision(settings, source, transcript, edit.model_copy(update={"hook": "Other"}), dest, preview=True)
    wav = settings.root / "cache" / "audio.wav"
    run([settings.executable("ffmpeg"), "-v", "error", "-n", "-i", str(target), "-map", "0:a:0",
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], cwd=wav.parent)
    with wave.open(str(wav), "rb") as reader:
        samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
    def tone_at(second):
        start = round(16_000 * second)
        spectrum = np.abs(np.fft.rfft(samples[start:start + 3200] * np.hanning(3200)))
        return np.argmax(spectrum) * 5

    assert tone_at(0.3) == pytest.approx(220, abs=5)
    assert tone_at(0.85) == pytest.approx(880, abs=5)
    (dest / "captions.srt").write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        render_revision(settings, source, transcript, edit, dest, preview=True)


@pytest.mark.integration
@pytest.mark.parametrize("layout", ["fit", "crop", "roi", "split", "split_below", "pip"])
def test_real_final_and_preview_layouts(render_setup, layout):
    settings, source = render_setup
    edit = EditDecision(start_seconds=0, end_seconds=0.7, layout=layout, resolution=720, subtitle_style="word",
                        denoise=True, fade_in=True, facecam={"x": 0.6, "y": 0, "width": 0.4, "height": 0.4},
                        roi={"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5})
    preview = layout != "fit"
    destination = settings.root / "output" / layout
    assert render_revision(settings, source, timed_transcript(), edit, destination, preview=preview).is_file()
    info = json.loads((destination / "report.json").read_bytes())
    assert (info["width"], info["height"]) == ((360, 640) if preview else (720, 1280))


@pytest.mark.integration
@pytest.mark.parametrize("layout,stamps,expected", [
    ("track", [0.1, 1, 2, 3, 3.9], "track"),
    ("dynamic", [0.5, 1, 2, 3.2], "dynamic"),
    ("track", [1, 1.5], "fit"),
])
def test_real_tracked_layout_respects_source_clock_and_falls_back(render_setup, layout, stamps, expected):
    settings, source = render_setup
    points = [{"time": t, "box": {"x": 0.25 + t * 0.03, "y": 0.2, "width": 0.13, "height": 0.35}} for t in stamps]
    edit = EditDecision(start_seconds=0.1, end_seconds=3.9, cuts=[{"start": 1.25, "end": 1.65}],
                        layout=layout, track_id=2, subtitle_style="none")
    destination = settings.root / "output" / "tracked"
    target = render_revision(settings, source, timed_transcript(), edit, destination,
                             preview=True, track_points=points)
    info = json.loads((destination / "report.json").read_bytes())
    assert info["requested_layout"] == layout
    assert info["rendered_layout"] == expected
    assert info["duration"] == pytest.approx(3.4, abs=1/30)

    def top_brightness(position):
        raw = subprocess.check_output([settings.ffmpeg, "-v", "error", "-ss", str(position), "-i", str(target),
                                       "-vf", "crop=120:72:120:0,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"])
        return np.frombuffer(raw, dtype=np.uint8).mean()

    if expected == "dynamic":
        assert top_brightness(0.15) < 5
        assert top_brightness(1.6) > 15
        assert top_brightness(3.2) < 5
    elif expected == "track":
        assert top_brightness(0.15) > 15
    else:
        assert top_brightness(0.15) < 5


@pytest.mark.integration
def test_failed_and_cancelled_renders_publish_nothing(render_setup):
    settings, source = render_setup
    output = settings.root / "output" / "revisions"
    edit = EditDecision(start_seconds=0, end_seconds=1)
    def cancel():
        raise Cancelled("cancelled")
    with pytest.raises(Cancelled):
        render_revision(settings, source, timed_transcript(), edit, output, preview=True, cancel=cancel)
    assert not output.exists()
    bad = edit.model_copy(update={"end_seconds": 4.5})
    with pytest.raises(ValueError, match="past the end"):
        render_revision(settings, source, timed_transcript(), bad, output, preview=True)
    assert not output.exists()


@pytest.fixture
def clip_api(render_setup,clip_candidate):
    from threading import Event
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import Database
    from app.schemas import Campaign, Clip, JobRequest, Status
    from app.services.metadata import export_metadata
    from app.utils.files import write_json
    from app.v2.clips import router
    from app.v2.storage import migrate, seed

    settings, source = render_setup
    (settings.root / "campaigns").mkdir()
    preset = Campaign(name="Test", category="Experiment",min_duration=3,max_duration=4,
                      preferred_min=3,preferred_max=4)
    write_json(settings.root / "campaigns" / "default.json",preset)
    db = Database(settings.root / "data" / "jobs.sqlite3")
    db.initialize()
    migrate(db)
    job = db.create(JobRequest(filename=source.name,authorized=True,layout="fit"))
    folder = settings.root / "output" / job.job_id
    folder.mkdir()
    clip = Clip(**{**clip_candidate.model_dump(), "start_seconds":0, "end_seconds":4},
                clip_id="clip_01", file="clip_01.mp4",duration=4,technical_checks=[],manual_review=[])
    shutil.copyfile(source, folder / clip.file)
    write_json(folder / "transcript.json",timed_transcript())
    export_metadata(folder,[clip])
    db.finish(job.job_id,Status.COMPLETED)
    seed(settings,db)
    app = FastAPI()
    app.state.settings,app.state.database = settings,db
    app.state.worker = SimpleNamespace(wake=Event())
    app.include_router(router,prefix="/api/v2")
    with TestClient(app) as client:
        yield client,settings,db,f"{job.job_id}:clip_01"


def execute_render_task(settings,db,task_id):
    from app.v2.clips import process_render

    with db.transaction(write=True) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=? AND status='queued'",(task_id,)).fetchone()
        assert row
        conn.execute("UPDATE tasks SET status='working' WHERE id=?",(task_id,))
    process_render(settings,db,row,lambda: None)
    with db.transaction(write=True) as conn:
        conn.execute("UPDATE tasks SET status='completed' WHERE id=?",(task_id,))


@pytest.mark.integration
def test_metadata_suggestions_are_reviewed_and_versioned(clip_api, monkeypatch):
    from threading import Event
    from types import SimpleNamespace
    from app.v2 import metadata, tasks

    client, settings, db, key = clip_api
    base = "/api/v2/clips/" + key
    clip = client.get(base).json()
    fields = {k: clip[k] for k in metadata.PublishingMetadata.model_fields}
    fields.update(title="Suggested local title", instagram_caption="A bridge test",
                  tiktok_caption="Paper bridge", thumbnail_text="Bridge test")
    proposal = metadata.MetadataSuggestion(metadata=fields, alternative_hooks=["Does paper hold?"],
                                           evidence_quote="One middle three", evidence_event=None,
                                           editing_notes="Keep the shot through the result.")
    monkeypatch.setattr(metadata, "suggest", lambda *args: proposal)
    approved = client.post(base+"/review", json={"revision":1,"status":"approved"})
    assert approved.status_code == 200
    receipt = client.post(base+"/metadata/suggestion", json={"revision":1})
    assert receipt.status_code == 202
    assert client.post(base+"/metadata/suggestion", json={"revision":1}).json()["id"] == receipt.json()["id"]
    assert tasks.run_next(SimpleNamespace(database=db, settings=settings, stop=Event()))
    result = client.get(base+"/metadata/suggestion").json()
    assert result["status"] == "completed" and result["suggestion"]["metadata"] == fields
    assert client.get(base).json()["review"]["status"] == "approved"
    changed = client.patch(base, json={"revision":1,"edit":clip["edit"],"metadata":fields})
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2 and changed.json()["review"]["status"] == "pending"
    assert changed.json()["title"] == fields["title"]
    assert client.get(base+"/metadata/suggestion").json() is None
    assert client.post(base+"/metadata/suggestion", json={"revision":1}).status_code == 409


def test_metadata_requires_evidence_from_one_retained_span(clip_candidate):
    from app.schemas import Campaign
    from app.v2.metadata import MetadataSuggestion, validate_suggestion

    metadata = clip_candidate.model_dump(include={"hook","title","caption","description","hashtags"})
    metadata.update(instagram_caption="A paper bridge", tiktok_caption="The bridge held",
                    thumbnail_text="Paper bridge")
    candidate = {"metadata":metadata, "alternative_hooks":["What can paper hold?"],
                 "evidence_quote":"paper bridge held", "evidence_event":None, "editing_notes":"Keep the reveal."}

    def response():
        return MetadataSuggestion.model_validate(candidate)

    campaign = Campaign(name="Experiment", category="General")
    assert validate_suggestion(response(), ["The paper bridge held."], 0, campaign).evidence_quote == "paper bridge held"
    with pytest.raises(ValueError, match="outside"):
        validate_suggestion(response(), ["The paper", "bridge held."], 0, campaign)
    candidate.update(evidence_quote="", evidence_event=2)
    with pytest.raises(ValueError, match="available event"):
        validate_suggestion(response(), [], 1, campaign)


@pytest.mark.integration
def test_revision_review_export_flow_with_real_media(clip_api,monkeypatch):
    from app.v2 import runs

    client,settings,db,key = clip_api
    base = "/api/v2/clips/"+key
    hooks = []
    monkeypatch.setattr(runs,"dispatch_webhook",lambda _,kind,data: hooks.append((kind,data)))
    original = client.get(base).json()
    assert original["revision"] == 1 and original["hook_options"]
    assert client.get(base+"/media",headers={"Range":"bytes=0-7"}).status_code == 206
    assert client.post(base+"/render").status_code == 409
    assert client.get(base+"/download").status_code == 409
    edit = {**original["edit"],"start_seconds":0.1,"end_seconds":3.8,"resolution":720,"subtitle_style":"karaoke"}
    draft = client.patch(base,json={"revision":1,"edit":edit}).json()
    assert draft["revision"] == 2 and not draft["exported"]
    assert client.patch(base,json={"revision":1,"edit":edit}).status_code == 409
    approve = {"status":"approved","revision":2,"note":"Checked the new timing"}
    assert client.post(base+"/review",json=approve).status_code == 409
    task = client.post(base+"/preview").json()
    assert client.post(base+"/preview").json()["id"] == task["id"]
    execute_render_task(settings,db,task["id"])
    assert client.get(client.get(base).json()["rendered_preview"]).status_code == 200
    assert client.post(base+"/review",json=approve).status_code == 200
    exported = client.post("/api/v2/exports",json={"clip_ids":[key]}).json()
    assert exported["status"] == "awaiting_automation"
    assert hooks == [("export",{"export_id":exported["id"],"clip_ids":[key]})]
    callback = "/api/v2/internal/exports/"+exported["id"]+"/start"
    assert client.post(callback,json={**hooks[0][1],"export_id":"1"*32}).status_code == 409
    for _ in range(2):
        assert client.post(callback,json=hooks[0][1]).json()["status"] == "queued"
    execute_render_task(settings,db,exported["id"])
    assert client.post(callback,json=hooks[0][1]).json()["status"] == "completed"
    assert client.post(base+"/render").json()["id"] == exported["id"]
    assert client.get(base).json()["exported"] is True
    downloaded = client.get(base+"/download",headers={"Range":"bytes=0-31"})
    assert downloaded.status_code == 206 and len(downloaded.content) == 32
    assert client.post(base+"/review",json={**approve,"status":"rejected"}).status_code == 200
    assert client.get(base+"/download").status_code == 409
    with db.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2
        recorded = conn.execute("SELECT version,status FROM reviews ORDER BY seq").fetchall()
        assert [tuple(row) for row in recorded] == [(2,"edited"),(2,"approved"),(2,"rejected")]


def test_revoked_approval_is_checked_again_at_callback_and_publication(clip_api,monkeypatch):
    from app.v2 import clips, runs

    client,settings,db,key = clip_api
    monkeypatch.setattr(runs,"dispatch_webhook",lambda *args: None)
    base = "/api/v2/clips/"+key
    approve = {"status":"approved","revision":1,"note":""}
    assert client.post(base+"/review",json=approve).status_code == 200
    task_id = client.post(base+"/render").json()["id"]
    start = "/api/v2/internal/exports/"+task_id+"/start"
    data = {"export_id":task_id,"clip_ids":[key]}
    assert client.post(base+"/review",json={**approve,"status":"rejected"}).is_success
    assert client.post(start,json=data).status_code == 409
    assert client.post(base+"/review",json=approve).is_success
    assert client.post(start,json=data).status_code == 409
    new_id = client.post(base+"/render").json()["id"]
    assert new_id != task_id
    assert client.post(start.replace(task_id,new_id),json={**data,"export_id":new_id}).is_success

    def revoke_during_render(settings,source,transcript,edit,destination,**kwargs):
        client.post(base+"/review",json={**approve,"status":"rejected"}).raise_for_status()
        destination.mkdir(parents=True)
        return destination / "clip.mp4"

    monkeypatch.setattr(clips,"render_revision",revoke_during_render)
    with pytest.raises(ValueError,match="original approval"):
        execute_render_task(settings,db,new_id)
    assert client.get(base+"/download").status_code == 409
