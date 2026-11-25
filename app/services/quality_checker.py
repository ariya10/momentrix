from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.schemas import Campaign, Candidate, JobRequest
from app.services.audio import probe
from app.services.clip_validator import metadata_issues
from app.services.subtitles import Cue
from app.services.video_editor import HEIGHT, WIDTH
from app.utils.process import run

MANUAL_REVIEW = [
    "Check that the creator is visible and any gameplay or facecam remains readable.",
    "Listen for clear dialogue and check subtitles against the audio.",
    "Check that the hook matches the clip and the clip has a meaningful payoff.",
    "Verify source permission, creator identity and any campaign dates or visual requirements.",
    "Check for misleading edits, unauthorized material and prohibited campaign content.",
]


def quality_check(settings: Settings, target: Path, clip: Candidate, request: JobRequest,
                  campaign: Campaign, phrases: list[Cue], cancel: Callable[[], None]) -> list[str]:
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError("Clip file is missing or empty")
    media = probe(settings, target, cancel)
    expected = clip.end_seconds - clip.start_seconds
    slack = max(0.075, 1.5 / settings.fps)
    if not (request.min_duration - slack <= media.duration <= request.max_duration + slack
            and abs(media.duration - expected) <= slack):
        raise ValueError("Rendered duration does not match the selected clip")
    if ((media.width, media.height) != (WIDTH, HEIGHT) or media.sample_aspect_ratio != "1:1"
            or media.video_codec != "h264" or media.pixel_format != "yuv420p"
            or abs(media.fps - settings.fps) > 0.1 or "aac" not in media.audio_codecs):
        raise ValueError("Rendered media does not match the H.264/AAC vertical export settings")
    if any(not 0 <= cue.start < cue.end <= min(expected, media.duration) + 1e-6 for cue in phrases):
        raise ValueError("Subtitle cue lies outside the clip's duration")
    issues = metadata_issues(clip, campaign)
    if issues:
        raise ValueError("; ".join(issues))
    run([settings.executable("ffmpeg"), "-v", "error", "-xerror", "-nostdin",
         "-protocol_whitelist", "file", "-i", str(target), "-map", f"0:{media.video_stream}",
         "-map", f"0:{media.audio_streams[0]}", "-f", "null", "-"], cwd=target.parent,
        check_cancel=cancel, timeout=settings.ffmpeg_timeout)
    return ["Decoded video and audio", "Checked duration, 9:16 resolution, frame rate and codecs",
            "Checked subtitle timing and campaign metadata"]
