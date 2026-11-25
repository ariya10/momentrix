import json
from bisect import bisect_left, bisect_right
from collections.abc import Callable

from app.config import ROOT, Settings
from app.schemas import Campaign, Candidate, Transcript
from app.services.chunking import Chunk, chunks
from app.services.ollama_client import ask, availability


def eligible_ranges(rows: list, minimum: float, maximum: float,
                    preferred_min: float, preferred_max: float) -> list[list[float]]:
    starts, ends = sorted({row[0] for row in rows}), sorted({row[1] for row in rows})
    if len(starts) > 48:
        starts = [starts[round(index * (len(starts) - 1) / 47)] for index in range(48)]
    # Give the model valid full-clip ranges. A typical row contains only a few seconds of dialogue.
    result = []
    for start in starts:
        left = bisect_left(ends, round(start + minimum, 3))
        right = bisect_right(ends, round(start + maximum, 3))
        possible = ends[left:right]
        if not possible:
            continue
        preferred = (preferred_min + preferred_max) / 2
        near = min(possible, key=lambda end: abs(end - start - preferred))
        for end in sorted({possible[0], near, possible[-1]}):
            result.append([start, end])
    return result


def select(settings: Settings, transcript: Transcript, campaign: Campaign,
           minimum: float, maximum: float, count: int, cancel: Callable[[], None],
           progress: Callable[[float], None], *, events=None) -> list[tuple[Candidate, Chunk]]:
    system = "\n".join((ROOT / "prompts" / name).read_text(encoding="utf-8")
                       for name in ("highlight_selection.txt", "metadata_generation.txt"))
    windows = []
    for window in chunks(transcript.segments):
        rows = [json.loads(row) for row in window.rows]
        ranges = eligible_ranges(rows, minimum, maximum, campaign.preferred_min, campaign.preferred_max)
        if ranges:
            windows.append((window, rows, ranges))
    candidates = []
    if windows:
        running, installed = availability(settings)
        if not running:
            raise RuntimeError("Cannot reach the local Ollama service.")
        if not installed:
            raise RuntimeError(f"Ollama model {settings.ollama_model} is not installed locally.")
    for index, (window, rows, ranges) in enumerate(windows, 1):
        cancel()
        limit = max(1, int((window.end - window.start) / minimum))
        measurements = {}
        if events is not None:
            from app.v2.analysis import best_events
            measurements["measured_events"] = [item.model_dump() for item in
                                               best_events(events, window.start, window.end, limit=12)]
        responses = ask(settings, system, {
            **measurements,
            "constraints": {"min_duration": minimum, "max_duration": maximum,
                            "target_per_window": min(6, count, limit),
                            "campaign": campaign.model_dump(mode="json", exclude_defaults=True)},
            "window": [round(window.start, 3), round(window.end, 3)],
            "transcript_rows": rows,
        }, cancel, ranges=ranges, keep_alive="2m" if index < len(windows) else 0)
        candidates.extend((candidate, window) for candidate in responses)
        progress(index / len(windows))
    return candidates
