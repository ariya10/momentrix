import shutil
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import JobRequest
from app.services import audio, subtitles, video_editor
from app.services.campaigns import load_campaign, resolve_request
from app.services.ollama_client import ask, availability
from app.services.quality_checker import quality_check
from app.utils.process import run

pytestmark = pytest.mark.integration


@pytest.fixture
def media_settings(settings):
    real = Settings()
    ffmpeg, ffprobe = real.executable("ffmpeg"), real.executable("ffprobe")
    if not shutil.which(ffmpeg) or not shutil.which(ffprobe):
        pytest.skip("FFmpeg and FFprobe are unavailable")
    return settings.model_copy(update={"ffmpeg": ffmpeg, "ffprobe": ffprobe, "cpu_threads": 2})


@pytest.mark.parametrize("layout", ["fit", "crop", "roi", "split"])
def test_ffmpeg_renders_verified_layouts(media_settings, clip_candidate, transcript, layout):
    settings = media_settings
    ffmpeg = settings.executable("ffmpeg")
    folder = settings.root / "input"
    source = folder / "Vidéo café & 01.mp4"
    run([ffmpeg, "-v", "error", "-n", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "4",
         "-c:v", "libx264", "-c:a", "aac", str(source)], cwd=folder)
    cancel = lambda: None
    media = audio.probe(settings, source, cancel)
    assert media.audio_streams and media.aspect_ratio == "4:3"
    wav = folder / "source.wav"
    audio.extract(settings, source, media.audio_streams[0], wav, cancel)
    assert wav.stat().st_size > 44
    target = folder / "clip_01.mp4"
    crop = {"x": 0, "y": 0, "width": 120, "height": 100}
    request = JobRequest(filename=source.name, authorized=True, layout=layout, roi=crop,
                         facecam=crop, gameplay={"x": 80, "y": 20, "width": 220, "height": 200},
                         min_duration=3, max_duration=4, opening_hook=True, quality="low",
                         normalize_audio=layout == "split", fade_in=layout == "crop")
    campaign = load_campaign(settings.root, "default").model_copy(update={"min_duration": 3})
    request = resolve_request(request, campaign)
    clip = clip_candidate.model_copy(update={"start_seconds": 0.5, "end_seconds": 3.5})
    phrases = subtitles.cues(transcript, clip.start_seconds, clip.end_seconds)
    _, ass = subtitles.write_subtitles(folder, "clip_01", clip, request, phrases)
    video_editor.render(settings, source, target, media, clip, request, ass, cancel)
    assert quality_check(settings, target, clip, request, campaign, phrases, cancel)


def test_video_without_an_audio_stream_completes_with_warnings(media_settings):
    settings = media_settings
    source = settings.root / "input" / "silent.mp4"
    run([settings.executable("ffmpeg"), "-v", "error", "-n", "-f", "lavfi", "-i",
         "color=size=64x64:rate=25", "-t", "1", "-c:v", "libx264", str(source)], cwd=source.parent)
    with TestClient(create_app(settings), base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        response = client.post("/jobs", json={"filename": source.name, "authorized": True})
        assert response.status_code == 202
        path = f"/jobs/{response.json()['job_id']}"
        deadline = monotonic() + 12
        while monotonic() < deadline:
            job = client.get(path).json()
            if job["finished_at"]:
                break
            sleep(0.1)
        assert job["status"] == "completed_with_warnings"
        assert "The source has no audio stream." in job["warnings"]
        assert client.get(f"{path}/clips").json() == []


def test_ollama_returns_a_valid_structured_response():
    settings = Settings()
    if not availability(settings)[1]:
        pytest.skip("The configured Ollama model is unavailable")
    result = ask(settings, 'Return the JSON object {"clips":[]}.', {"transcript_rows": []},
                 lambda: None, ranges=[])
    assert result == []
