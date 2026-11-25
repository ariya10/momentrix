"""Timestamped measurements from downsampled local media and transcribed words."""
from collections import deque
from math import hypot, log10
from pathlib import Path
from statistics import median
import wave

import numpy as np

from app.schemas import MeasuredCandidate, Scores, SignalEvent, Transcript
from app.services.chunking import Chunk

AUDIO = {"audio_peak", "audio_rise"}
VISUAL = {"scene_change", "motion"}


def event(start, end, signal, strength, detail, confidence):
    return SignalEvent(start=round(start, 4), end=round(end, 4), signal=signal,
                       strength=round(min(1., max(0., strength)), 4), detail=detail,
                       confidence=round(confidence, 4))


def audio_features(path: Path, duration: float, cancel):
    """Analyze half-second PCM windows. Read sequentially, keeping only scalar measurements."""
    levels, peaks = [], []
    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise ValueError("Audio features require signed 16-bit mono PCM")
        rate = stream.getframerate()
        while samples := stream.readframes(max(1, rate // 2)):
            cancel()
            pcm = np.frombuffer(samples, dtype="<i2").astype(np.float32) / 32768.
            levels.append(float(np.sqrt(np.mean(pcm * pcm))))
            peaks.append(float(np.max(np.abs(pcm))))
    if not levels:
        return [], [], []
    baseline = max(0.025, float(np.percentile(levels, 70)))
    history = deque(maxlen=10)
    events = []
    quiet_since = None
    rows = []
    for i, (rms, peak) in enumerate(zip(levels, peaks)):
        at = i * 0.5
        if at >= duration:
            break
        end = min(duration, at + 0.5)
        db = 20 * log10(max(1e-5, rms))
        rows.append([at, round(db, 1), round(peak, 4)])
        if db < -50:
            if quiet_since is None:
                quiet_since = at
        elif quiet_since is not None:
            if at - quiet_since >= 1:
                events.append(event(quiet_since, at, "silence", 1, "Mono RMS stayed below -50 dBFS.", 0.95))
            quiet_since = None
        if history:
            rise = 20 * log10(max(1e-5, rms) / max(0.002, median(history)))
            if rise >= 6 and rms >= 0.025:
                events.append(event(at, end, "audio_rise", rise / 18, f"RMS rose {rise:.1f} dB over the preceding windows.", 0.95))
        if rms >= max(0.04, baseline * 1.45) and peak >= 0.20:
            events.append(event(at, end, "audio_peak", min(rms / baseline / 3, peak),
                                f"Measured peak {peak:.2f} full scale and RMS {db:.1f} dBFS.", 0.95))
        history.append(rms)
    if quiet_since is not None and duration - quiet_since >= 1:
        events.append(event(quiet_since, min(duration, len(levels) * 0.5), "silence", 1,
                            "Mono RMS stayed below -50 dBFS.", 0.95))
    waveform = [round(float(np.max(part)), 4) for part in np.array_split(levels, min(480, len(levels)))]
    return waveform, events, rows


def speech_features(transcript: Transcript):
    events = []
    for segment in transcript.segments:
        length = segment.end - segment.start
        if length >= 1 and len(segment.words) >= 4:
            rate = len(segment.words) / length
            if rate >= 3.5:
                events.append(event(segment.start, segment.end, "speech_rate", rate / 6,
                                    f"{len(segment.words)} transcribed words in {length:.2f} seconds.", 0.75))
    return events


class FaceTracks:
    """Nearest-neighbour association of anonymous sample detections in normalized coordinates."""

    def __init__(self, step):
        self.step = step
        self.tracks = []

    def update(self, at, boxes):
        pairs = []
        for track in self.tracks:
            last = track["points"][-1]
            if at - last["time"] > 2.1 * self.step and track["lost_at"] is None:
                track["lost_at"] = last["time"] + self.step
            if track["lost_at"] is not None:
                continue
            old = last["box"]
            for index, box in enumerate(boxes):
                if max(box["width"], old["width"]) > 2 * min(box["width"], old["width"]):
                    continue
                dx = old["x"] - box["x"] + (old["width"] - box["width"]) / 2
                dy = old["y"] - box["y"] + (old["height"] - box["height"]) / 2
                distance = hypot(dx, dy)
                if distance <= max(0.08, 0.85 * old["width"]):
                    pairs.append((distance, track["id"], index))
        used_tracks, used_boxes = set(), set()
        for _, track_id, index in sorted(pairs):
            if track_id in used_tracks or index in used_boxes:
                continue
            track = self.tracks[track_id - 1]
            old, box = track["points"][-1]["box"], boxes[index]
            smooth = {k: round(old[k] * 0.35 + box[k] * 0.65, 6) for k in old}
            track["points"].append({"time": at, "box": smooth})
            used_tracks.add(track_id)
            used_boxes.add(index)
        for index, box in enumerate(boxes):
            if index not in used_boxes:
                self.tracks.append({"id": len(self.tracks) + 1, "lost_at": None,
                                    "points": [{"time": at, "box": box}]})


def best_events(events, start, end, limit=12):
    relevant = (e for e in events if e.start >= start and e.end <= end and e.signal != "silence")
    return sorted(relevant, key=lambda e: (-e.strength, e.start))[:limit]


def score_clip(clip, events, weights, audio_available, visual_available):
    relevant = best_events(events, clip.start_seconds, clip.end_seconds, limit=500)
    components = {}
    if getattr(clip, "evidence_mode", "dialogue") == "dialogue":
        maximums = {"hook":25, "entertainment":25, "standalone":20, "payoff":15, "relevance":15}
        components.update({key: round(getattr(clip.score_breakdown, key) / limit, 4)
                           for key, limit in maximums.items()})
    for name, signals, available in (("audio", AUDIO, audio_available), ("visual", VISUAL, visual_available)):
        if available:
            components[name] = max((e.strength for e in relevant if e.signal in signals), default=0.)
    total_weight = sum(weights.get(k, 0) for k in components)
    if total_weight <= 0:
        raise ValueError("No measured score component has a positive configured weight")
    score = round(100 * sum(value * weights.get(k, 0) for k, value in components.items()) / total_weight)
    # An evidence-coverage indicator for human review; this is not calibrated probability.
    coverage = round(total_weight / sum(weights.values()), 3)
    return MeasuredCandidate.model_validate({**clip.model_dump(), "score":score, "component_scores":components,
                                            "confidence":coverage,"evidence":relevant[:12]})


def signal_candidates(events, duration, minimum, maximum, preferred, limit):
    """Candidates anchored to measured source events when there is no transcript."""
    if duration < minimum:
        return []
    length = min(duration, maximum, max(minimum, preferred))
    result = []
    for item in sorted(events, key=lambda e: -e.strength):
        if item.signal not in AUDIO | VISUAL or item.strength < 0.65:
            continue
        start = max(0., min(duration - length, item.start - length * 0.4))
        end = start + length
        if item.end > end or any(abs(start - other.start_seconds) < length * 0.6 for other, _ in result):
            continue
        names = {"motion":"Movement in frame", "scene_change":"A visual transition",
                 "audio_peak":"A peak in the audio", "audio_rise":"A rise in the audio"}
        title = names[item.signal]
        clip = MeasuredCandidate(start_seconds=start, end_seconds=end, title=title, hook=title, caption=item.detail,
                         description=item.detail, hashtags=[], category=item.signal, score=0,
                         score_breakdown=Scores(hook=0, entertainment=0, standalone=0, payoff=0, relevance=0),
                         selection_reason=f"Review the measured change at {item.start:.2f}s.",
                         supporting_transcript="", evidence_mode="signal", evidence=[item],
                         review_flags=["No dialogue evidence. Review context and meaning."])
        result.append((clip, Chunk(start,end,())))
        if len(result) >= limit:
            break
    return result
