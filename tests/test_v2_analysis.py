from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import shutil

import numpy as np
import pytest

from app.config import Settings
from app.database import Database
from app.schemas import Campaign, JobRequest, SignalEvent, Status, Transcript
from app.services import audio
from app.services.clip_validator import rank
from app.services.transcription import cache_key
from app.utils.process import run
from app.v2.analysis import FaceTracks, audio_features, event, score_clip, signal_candidates
from app.v2.assets import asset_record
from app.v2.media_assets import cache_folder, prepare_asset, preview_path, thumbnail_path, timeline
from app.v2.presets import processing_settings
from app.v2.storage import migrate
from app.workers.job_worker import Worker


def test_sampled_tracks_smooth_multiple_faces_and_end_after_loss():
    tracks = FaceTracks(1)
    left = {"x":0.1,"y":0.1,"width":0.1,"height":0.2}
    right = {**left,"x":0.8}
    tracks.update(0, [left,right])
    tracks.update(1, [right,{**left,"x":0.14}])
    assert [t["id"] for t in tracks.tracks] == [1,2]
    assert 0.1 < tracks.tracks[0]["points"][1]["box"]["x"] < 0.14
    for at in (2,3,4):
        tracks.update(at,[])
    tracks.update(5,[left])
    assert tracks.tracks[0]["lost_at"] == 2 and tracks.tracks[2]["id"] == 3


def test_processing_presets_isolate_transcripts_and_preserve_balanced_cache(settings):
    source = settings.root / "input" / "fixture.mp4"
    source.write_bytes(b"stable local bytes")
    fast = processing_settings(settings, "fast")
    balanced = processing_settings(settings, "balanced")
    quality = processing_settings(settings, "quality")

    assert balanced is settings
    assert (fast.whisper_beam_size, balanced.whisper_beam_size, quality.whisper_beam_size) == (1, 3, 5)
    assert fast.crf > balanced.crf > quality.crf
    assert (fast.ffmpeg_preset, balanced.ffmpeg_preset, quality.ffmpeg_preset) == ("ultrafast", "veryfast", "medium")
    assert len({cache_key(profile,source,lambda: None) for profile in (fast,balanced,quality)}) == 3


def test_audio_analysis_measures_rise_silence_and_waveform(tmp_path):
    import wave
    target = tmp_path / "pulse.wav"
    rate = 8000
    time = np.arange(rate) / rate
    wave_data = np.concatenate([np.zeros(rate*2),np.sin(440 * 2 * np.pi * time) * 0.6])
    with wave.open(str(target),"wb") as handle:
        handle.setparams((1,2,rate,0,"NONE","not compressed"))
        handle.writeframes((32767 * wave_data).astype("<i2").tobytes())
    waveform, events, rows = audio_features(target, 3, lambda: None)
    assert len(waveform) == len(rows) == 6
    assert max(waveform[:4]) == 0 and waveform[-1] > .4
    assert any(e.signal=="silence" and e.start==0 and e.end==2 for e in events)
    assert any(e.signal=="audio_rise" and e.start==2 for e in events)


def test_weight_renormalization_and_threshold_validation(settings, clip_candidate):
    weights = {"hook":20,"audio":80}
    clip = score_clip(clip_candidate, [], weights, False, False)
    assert clip.score == 80
    assert clip.confidence == 0.2
    assert "audio" not in clip.component_scores
    assertion = event(2,3,"scene_change",.9,"Observed visual change.",.8)
    candidates = signal_candidates([assertion],12,4,12,7,2)
    transcript = Transcript(source_filename="x.mp4",source_duration=12,language=None,segments=[])
    campaign = Campaign(name="Open",category="general",min_duration=3,max_duration=12)
    assert rank(candidates, transcript, campaign, 4,12,1,events=[],weights=settings.rank_weights,
                visual_available=True).rejections == {"missing measured evidence":1}
    kept = rank(candidates,transcript,campaign,4,12,1,events=[assertion],weights=settings.rank_weights,
                visual_available=True).clips
    assert kept[0].supporting_transcript == "" and kept[0].score == 90
    assert kept[0].component_scores == {"visual":0.9}
    assert rank(candidates,transcript,campaign.model_copy(update={"required_keywords":["winner"]}),
                4,12,1,events=[assertion],weights=settings.rank_weights,visual_available=True).rejections


@pytest.mark.integration
def test_v2_silent_visual_job_prepares_proxy_and_exports_from_evidence(settings):
    real = Settings()
    if not all(shutil.which(real.executable(name)) for name in ("ffmpeg","ffprobe")):
        pytest.skip("Requires FFmpeg and FFprobe")
    settings = settings.model_copy(update={"ffmpeg":real.executable("ffmpeg"),"ffprobe":real.executable("ffprobe"),
                                           "visual_sample_seconds":0.5,"cpu_threads":2})
    source = settings.root / "input" / "transition.mkv"
    run([settings.ffmpeg,"-v","error","-n","-f","lavfi","-i","color=c=white:s=160x90:r=10:d=2",
         "-f","lavfi","-i","color=c=black:s=160x90:r=10:d=2","-filter_complex","[0:v][1:v]concat=n=2:v=1:a=0",
         "-threads:v","1","-c:v","ffv1",str(source)],cwd=source.parent)
    db = Database(settings.root/"data"/"jobs.sqlite3")
    db.initialize()
    migrate(db)
    media = audio.probe(settings,source,lambda:None)
    stamp = datetime.now(UTC).isoformat()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    campaign = Campaign(name="Visual test",category="general",min_duration=3,max_duration=4)
    req = JobRequest(filename=source.name,authorized=True,min_duration=3,max_duration=4,count=1,
                     campaign="database_only",layout="fit",quality="low",subtitles=False)
    job = db.create(req)
    with db.transaction(write=True) as c:
        c.execute("INSERT INTO projects VALUES ('p','test','general',1,?,0)",(stamp,))
        c.execute("INSERT INTO assets VALUES ('a','p',?,?,?,?)",
                  (source.name,source.name,digest,json.dumps(asdict(media))))
        c.execute("""INSERT INTO runs(id,project_id,asset_id,correlation_id,idempotency_key,status,created_at,
                  options,campaign,job_id) VALUES ('r','p','a','c','test','queued',?,?,?,?)""",
                  (stamp,req.model_dump_json(),campaign.model_dump_json(),job.job_id))
    manifest = prepare_asset(settings,db,"a")
    row = asset_record(db,"a")
    assert not manifest["audio_available"] and not manifest["waveform"]
    assert manifest["thumbnail_times"] == pytest.approx([i/2 for i in range(8)],abs=.001)
    assert any(e["signal"]=="scene_change" and e["end"] == 2 for e in manifest["events"])
    assert thumbnail_path(settings,row).is_file()
    assert timeline(settings,row)["thumbnails"][1]["url"].endswith("thumbnail?index=1")
    assert audio.probe(settings,preview_path(settings,row),lambda:None).video_codec=="h264"
    assert prepare_asset(settings,db,"a") == manifest
    fast = prepare_asset(settings,db,"a",preset="fast")
    quality = prepare_asset(settings,db,"a",preset="quality")
    assert fast["sample_count"] < manifest["sample_count"] < quality["sample_count"]
    assert prepare_asset(settings,db,"a",preset="fast") == fast
    assert prepare_asset(settings,db,"a",preset="quality") == quality
    assert cache_folder(settings,row,preset="fast") != cache_folder(settings,row,preset="quality")
    Worker(settings,db).process(db.claim())
    assert db.get(job.job_id).status in {Status.COMPLETED,Status.WARNINGS}
    folder = settings.root/"output"/job.job_id
    clips = json.loads((folder/"clips.json").read_text(encoding="utf-8"))
    assert clips[0]["evidence_mode"] == "signal" and not clips[0]["supporting_transcript"]
    assert clips[0]["component_scores"]["visual"] >= .85
    assert all(SignalEvent.model_validate(e).end <= clips[0]["end_seconds"] for e in clips[0]["evidence"])
    assert audio.probe(settings,folder/clips[0]["file"],lambda:None).audio_codecs == ("aac",)
