import re
from collections import Counter
from dataclasses import dataclass

from app.schemas import Campaign, Candidate, Metadata, Transcript
from app.services.chunking import Chunk


@dataclass(frozen=True)
class RankedSelection:
    clips: list[Candidate]
    rejections: dict[str, int]
    campaign_issues: dict[str, int]


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def includes(text: str, requirement: str) -> bool:
    needle = " ".join(tokens(requirement))
    return bool(needle) and f" {needle} " in f" {' '.join(tokens(text))} "


def metadata_issues(metadata: Metadata, campaign: Campaign) -> list[str]:
    issues = [f"Missing hook reference to {term}" for term in campaign.hook_requires
              if not includes(metadata.hook, term)]
    issues += [f"Missing caption reference to {term}" for term in campaign.caption_requires
               if not includes(metadata.caption, term)]
    tags = {tag.casefold() for tag in metadata.hashtags}
    issues += [f"Missing required hashtag {tag}" for tag in campaign.required_hashtags
               if tag.casefold() not in tags]
    return issues


def transcript_text(transcript: Transcript, start: float, end: float) -> str:
    parts = []
    for segment in transcript.segments:
        if segment.end <= start or segment.start >= end:
            continue
        if segment.words:
            parts.extend(w.text for w in segment.words if w.start >= start - 0.005 and w.end <= end + 0.005)
        elif segment.start >= start - 0.005 and segment.end <= end + 0.005:
            parts.append(segment.text)
    return " ".join(parts)


def snap(transcript: Transcript, start: float, end: float) -> tuple[float, float]:
    starts, ends = [], []
    for segment in transcript.segments:
        if segment.end < start - 1 or segment.start > end + 1:
            continue
        starts.append(segment.start)
        ends.append(segment.end)
        for word in segment.words:
            starts.append(word.start)
            ends.append(word.end)
    before = [time for time in starts if start - 0.8 <= time <= start + 0.005]
    after = [time for time in ends if end - 0.005 <= time <= end + 0.8]
    return min(start, max(before, default=start)), max(end, min(after, default=end))


def rank(candidates: list[tuple[Candidate, Chunk]], transcript: Transcript, campaign: Campaign,
         minimum: float, maximum: float, count: int, *, events=None, weights=None,
         audio_available=False, visual_available=False) -> RankedSelection:
    rejected: Counter[str] = Counter()
    campaign_issues: Counter[str] = Counter()
    valid = []
    for candidate, window in candidates:
        start, end = candidate.start_seconds, candidate.end_seconds
        if not (window.start - 0.001 <= start < end <= window.end + 0.001
                and 0 <= start < end <= transcript.source_duration + 0.001):
            rejected["timestamps"] += 1
            continue
        end = min(end, transcript.source_duration)
        snapped_start, snapped_end = snap(transcript, start, end)
        if minimum <= snapped_end - snapped_start <= maximum:
            start, end = snapped_start, snapped_end
        if not minimum <= end - start <= maximum:
            rejected["duration"] += 1
            continue
        evidence = transcript_text(transcript, start, end)
        if getattr(candidate, "evidence_mode", "dialogue") == "signal":
            from app.v2.analysis import AUDIO, VISUAL
            if not events or not any(
                measured in candidate.evidence and measured.signal in AUDIO | VISUAL
                and measured.strength >= .65 and start <= measured.start < measured.end <= end
                for measured in events
            ):
                rejected["missing measured evidence"] += 1
                continue
        elif len(tokens(candidate.supporting_transcript)) < 3 or not includes(evidence, candidate.supporting_transcript):
            rejected["missing transcript evidence"] += 1
            continue
        issues = metadata_issues(candidate, campaign)
        issues.extend(f"Missing spoken keyword {keyword}" for keyword in campaign.required_keywords
                      if not includes(evidence, keyword))
        if issues:
            rejected["campaign requirements"] += 1
            campaign_issues.update(dict.fromkeys(issues, 1))
            continue
        candidate = candidate.model_copy(update={"start_seconds": start, "end_seconds": end,
                                                 "score": candidate.score_breakdown.total})
        if events is not None:
            from app.v2.analysis import score_clip
            candidate = score_clip(candidate, events, weights, audio_available, visual_available)
        valid.append(candidate)

    def priority(clip: Candidate) -> tuple[int, float, float]:
        length = clip.end_seconds - clip.start_seconds
        distance = max(campaign.preferred_min - length, length - campaign.preferred_max, 0)
        return -clip.score, distance, clip.start_seconds

    chosen: list[Candidate] = []
    for clip in sorted(valid, key=priority):
        start, end = clip.start_seconds, clip.end_seconds
        if any(
            max(0, min(end, other.end_seconds) - max(start, other.start_seconds))
            / min(end - start, other.end_seconds - other.start_seconds) >= 0.45
            or (clip.supporting_transcript and tokens(clip.supporting_transcript) == tokens(other.supporting_transcript))
            for other in chosen
        ):
            rejected["duplicate or overlap"] += 1
        elif len(chosen) < count:
            chosen.append(clip)
    return RankedSelection(chosen, dict(rejected), dict(campaign_issues))
