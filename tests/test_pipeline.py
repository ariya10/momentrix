import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import JobRequest, Segment
from app.services.audio import Media
from app.services.campaigns import load_campaign, resolve_request
from app.services.chunking import Chunk, chunks
from app.services.clip_selector import eligible_ranges
from app.services.clip_validator import rank
from app.services.ollama_client import parse_response
from app.services.subtitles import cues, stamp, write_subtitles
from app.services.transcription import cache_key, cached_transcript
from app.services.video_editor import render_command
from app.utils.files import child, source_path, video_name, write_json


def test_chunking_keeps_absolute_times_and_overlap():
    segments = [Segment(start=t, end=t + 10, text=f"Speech at {t}") for t in range(0, 630, 10)]
    windows = list(chunks(segments))
    assert [(window.start, window.end) for window in windows] == [(0, 300), (240, 540), (480, 630)]
    assert json.loads(windows[1].rows[0]) == [240, 250, "Speech at 240"]


def test_chunking_character_budget_preserves_valid_json():
    items = [Segment(start=t, end=t + 3, text='"quoted\\text 🧪"' * 50) for t in (10, 20, 30)]
    windows = list(chunks(items, budget=128))
    assert len(windows) == len(items)
    assert all(len("\n".join(window.rows).encode("utf-8")) < 128 for window in windows)
    assert [json.loads(window.rows[0])[0] for window in windows] == [10, 20, 30]


def test_ollama_requires_schema(clip_candidate):
    entry = clip_candidate.model_dump(exclude={"start_seconds", "end_seconds"})
    good = json.dumps({"clips": [{**entry, "range_id": 0}]})
    ranges = [[0, 30]]
    assert parse_response({"message": {"content": good}}, ranges) == [clip_candidate]
    with pytest.raises(ValueError, match="unknown interval"):
        parse_response({"message": {"content": good}}, [])
    for invalid in ("{wrong", '{"clips":[{}]}'):
        with pytest.raises(ValidationError):
            parse_response({"message": {"content": invalid}}, ranges)
    with pytest.raises(ValueError):
        parse_response({"done_reason": "length", "message": {"content": good}}, ranges)


def test_ollama_canonicalizes_bare_hashtags(clip_candidate):
    content = clip_candidate.model_dump(exclude={"start_seconds", "end_seconds"})
    content.update(hashtags=["PaperBridge"], range_id=0)
    payload = {"message": {"content": json.dumps({"clips": [content]})}}
    assert parse_response(payload, [[0, 30]])[0].hashtags == ["#PaperBridge"]


def test_suggested_ranges_cover_full_clips():
    rows = [[0, 3.48, "one"], [4.46, 9.46, "two"], [11, 22.94, "three"], [24.02, 41.3, "four"]]
    ranges = eligible_ranges(rows, 20, 60, 30, 45)
    assert [0, 41.3] in ranges
    assert all(20 <= end - start <= 60 for start, end in ranges)
    assert all(start in {row[0] for row in rows} and end in {row[1] for row in rows} for start, end in ranges)


def test_candidate_ranking_rejects_unsupported_ranges_and_evidence(settings, transcript, clip_candidate):
    valid = clip_candidate
    best = clip_candidate.model_copy(update={
        "start_seconds": 60, "end_seconds": 90, "supporting_transcript": "Three mugs sat upright.",
        "score_breakdown": clip_candidate.score_breakdown.model_copy(update={"hook": 25}),
    })
    candidates = [valid, valid, best,
                  valid.model_copy(update={"start_seconds": -1}),
                  valid.model_copy(update={"end_seconds": 5}),
                  valid.model_copy(update={"end_seconds": 121}),
                  valid.model_copy(update={"supporting_transcript": "The cave fell down."})]
    window = Chunk(0, 120, ())
    campaign = load_campaign(settings.root, "default")
    result = rank([(candidate, window) for candidate in candidates], transcript, campaign, 20, 60, 10)
    assert [clip.score for clip in result.clips] == [87, 82]
    assert [clip.start_seconds for clip in result.clips] == [60, 0]
    assert result.rejections == {"duplicate or overlap": 1, "timestamps": 2, "duration": 1,
                                "missing transcript evidence": 1}


def test_distinct_evidence_does_not_bypass_overlap(settings, transcript, clip_candidate):
    earlier = clip_candidate.model_copy(update={"end_seconds": 25})
    later = clip_candidate.model_copy(update={"start_seconds": 1, "end_seconds": 30,
                                             "supporting_transcript": "paper bridge held"})
    window = Chunk(0, 30, ())
    result = rank([(earlier, window), (later, window)], transcript,
                  load_campaign(settings.root, "default"), 20, 60, 10)
    assert len(result.clips) == 1
    assert result.rejections == {"duplicate or overlap": 1}


def test_campaign_authorization_rules_and_metadata(settings, transcript, clip_candidate):
    campaign = load_campaign(settings.root, "kai_cenat")
    assert campaign.language == "en"
    assert campaign.required_hashtags == ["#KAICENAT"]
    with pytest.raises(ValueError, match="permission"):
        resolve_request(JobRequest(filename="a.mp4"), campaign)
    with pytest.raises(ValueError, match="campaign range"):
        resolve_request(JobRequest(filename="a.mp4", authorized=True, max_duration=61), campaign)
    request = resolve_request(JobRequest(filename="a.mp4", authorized=True), campaign)
    assert (request.layout, request.count, request.min_duration, request.max_duration) == ("fit", 10, 20, 60)
    result = rank([(clip_candidate, Chunk(0, 30, ()))], transcript, campaign, 20, 60, 10)
    assert result.clips == []
    assert result.rejections == {"campaign requirements": 1}
    assert result.campaign_issues == {
        "Missing hook reference to Kai Cenat": 1,
        "Missing required hashtag #KAICENAT": 1,
    }


@pytest.mark.parametrize("name", ["../film.mp4", "C:\\film.mp4", "film.mp4:stream", "aux.mp4", "x.MP3", "a.mkv "])
def test_windows_paths_reject_unsafe_names(name):
    with pytest.raises(ValueError):
        video_name(name)


def test_unicode_paths_and_file_access(settings):
    name = "Crème brûlée 01.MOV"
    source = settings.root / "input" / name
    source.write_bytes(b"clip")
    assert source_path(source.parent, name, 10) == source
    with pytest.raises(ValueError):
        child(source.parent, "../anything")
    with pytest.raises(ValueError):
        source_path(source.parent, name, 2)


def test_transcript_cache_uses_contents_and_current_filename(settings, transcript):
    original = settings.root / "input" / "original.mp4"
    renamed = original.with_name("renamed.mp4")
    original.write_bytes(b"original bytes")
    renamed.write_bytes(original.read_bytes())
    key = cache_key(settings, original, lambda: None)
    write_json(key, transcript)
    assert cache_key(settings, renamed, lambda: None) == key
    assert cached_transcript(key, renamed).source_filename == "renamed.mp4"
    renamed.write_bytes(b"changed bytes")
    assert cache_key(settings, renamed, lambda: None) != key


def test_subtitles_use_clip_relative_word_timings(tmp_path, transcript, clip_candidate):
    phrases = cues(transcript, 1, 21)
    assert phrases[0].start == 0
    assert phrases[-1].end <= 20
    assert all(len(cue.lines) <= 2 for cue in phrases)
    request = JobRequest(filename="a.mp4", opening_hook=True, subtitle_position="top")
    srt, ass = write_subtitles(tmp_path, "clip_01", clip_candidate, request, phrases)
    assert "00:00:00,000 --> " in (tmp_path / srt).read_text("utf-8")
    assert "Dialogue: 1,0:00:00.00,0:00:03.00,Hook" in (tmp_path / ass).read_text("utf-8")
    assert stamp(3661.005) == "01:01:01,005"


def test_ffmpeg_command_keeps_source_and_ass_filter_separate(settings: Settings, clip_candidate):
    source = Path("D:/videos/Crème et thé.mp4")
    media = Media(90, 1280, 720, 30, "h264", "yuv420p", "1:1", 0, 2, (4,), ("aac",))
    request = JobRequest(filename=source.name, layout="crop", normalize_audio=True)
    args = render_command(settings, source, Path("D:/job/clip_01.mp4"), media, clip_candidate,
                          request, "clip_01.ass")
    assert args[args.index("-i") + 1] == str(source)
    graph = args[args.index("-filter_complex") + 1]
    assert graph.startswith("[0:2]")
    assert "crop=1080:1920" in graph and "ass=clip_01.ass" in graph
    assert "0:4" in args and "yuv420p" in args and "-n" in args
