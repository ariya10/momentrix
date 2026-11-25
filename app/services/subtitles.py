import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from app.schemas import Candidate, JobRequest, Transcript
from app.utils.files import atomic_text


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    lines: tuple[str, ...]


def cues(transcript: Transcript, start: float, end: float) -> list[Cue]:
    words = sorted((word for segment in transcript.segments if segment.start < end and segment.end > start
                    for word in segment.words if start - 0.005 <= word.start < word.end <= end + 0.005
                    and word.text.strip()), key=lambda word: word.start)
    result = []
    group = []
    for index, word in enumerate(words):
        word_text = " ".join(word.text.split())
        next_start = words[index + 1].start if index + 1 < len(words) else end
        group.append(word)
        duration = word.end - group[0].start
        phrase = re.sub(r"\s+([,.!?;:%])", r"\1", " ".join(" ".join(w.text.split()) for w in group))
        if (len(group) >= 5 or len(phrase) >= 36 or duration >= 2.4
                or word_text.endswith((".", "!", "?")) or next_start - word.end > 0.45
                or index + 1 == len(words)):
            begin = max(start, group[0].start)
            stop = min(end, next_start, max(word.end, min(begin + 0.75, word.end + 0.25)))
            if stop - begin >= 0.02:
                lines = textwrap.wrap(phrase, width=max(30, (len(phrase) + 1) // 2), break_on_hyphens=False)
                if len(lines) > 2:
                    split = len(phrase) // 2
                    lines = [phrase[:split].rstrip(), phrase[split:].lstrip()]
                result.append(Cue(begin - start, stop - start, tuple(lines)))
            group = []
    return result


def stamp(seconds: float, *, ass: bool = False, ceiling: bool = False) -> str:
    scale = 100 if ass else 1000
    ticks = int(seconds * scale + 1e-7) if ceiling else round(seconds * scale)
    total, fraction = divmod(ticks, scale)
    hours, leftover = divmod(total, 3600)
    minutes, remainder = divmod(leftover, 60)
    if ass:
        return f"{hours}:{minutes:02}:{remainder:02}.{fraction:02}"
    return f"{hours:02}:{minutes:02}:{remainder:02},{fraction:03}"


def ass_text(value: str) -> str:
    return value.replace("\\", "\\\u200b").replace("{", r"\{").replace("}", r"\}")


def write_subtitles(folder: Path, clip_id: str, clip: Candidate, request: JobRequest,
                    phrases: list[Cue]) -> tuple[str | None, str | None]:
    srt_name = f"{clip_id}.srt" if request.subtitles else None
    ass_name = f"{clip_id}.ass" if request.subtitles or request.opening_hook else None
    if srt_name:
        srt = []
        for index, cue in enumerate(phrases, 1):
            timing = f"{stamp(cue.start)} --> {stamp(cue.end, ceiling=True)}"
            # Players can interpret angle brackets as HTML even in plain SRT cues.
            lines = [line.replace("<", "＜").replace(">", "＞") for line in cue.lines]
            srt.append("\n".join([str(index), timing, *lines]))
        atomic_text(folder / srt_name, "\n\n".join(srt) + ("\n" if srt else ""))
    if ass_name:
        position = {"bottom": 2, "middle": 5, "top": 8}[request.subtitle_position]
        header = [
            "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920",
            "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Caption,{request.subtitle_font},52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H60000000,"
            f"-1,0,0,0,100,100,0,0,1,4,1,{position},95,95,315,1",
            f"Style: Hook,{request.subtitle_font},58,&H0095F1FF,&H0095F1FF,&H00000000,&H60000000,"
            f"-1,0,0,0,100,100,0,0,1,5,1,{2 if position == 8 else 8},95,95,185,1",
            "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        events = []
        for cue in phrases:
            begin, stop = stamp(cue.start, ass=True), stamp(cue.end, ass=True, ceiling=True)
            lines = r"\N".join(ass_text(line) for line in cue.lines)
            events.append(f"Dialogue: 0,{begin},{stop},Caption,,0,0,0,,{lines}")
        if request.opening_hook:
            hook = " ".join(clip.hook.split())
            lines = r"\N".join(ass_text(line) for line in textwrap.wrap(hook, width=30))
            stop = stamp(min(3.0, clip.end_seconds - clip.start_seconds), ass=True, ceiling=True)
            events.append(f"Dialogue: 1,0:00:00.00,{stop},Hook,,0,0,0,,{lines}")
        atomic_text(folder / ass_name, "\n".join([*header, *events]) + "\n")
    return srt_name, ass_name
