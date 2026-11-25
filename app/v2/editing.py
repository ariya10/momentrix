"""Source-timed, reversible edits rendered by the local media worker."""

import hashlib
import json
import math
import shutil
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

from filelock import FileLock
from pydantic import Field, StringConstraints, model_validator

from app.config import Settings
from app.schemas import Clip, JobRequest, Region, Seconds, StrictModel, Transcript
from app.services import audio
from app.services.subtitles import ass_text, stamp
from app.services.video_editor import SQUARE_PIXELS, crop_region, fit
from app.utils.files import write_json
from app.utils.process import run
from app.v2.tracking import build_dynamic_filter, build_track_filter

Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Position = Literal["bottom", "middle", "top"]
RenderMode = Literal["fit", "crop", "blur", "roi", "split", "split_below", "pip", "track", "dynamic"]
TRACK_LAYOUTS = {"track", "dynamic"}


class Interval(StrictModel):
    start: Seconds
    end: Seconds

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("End must be later than start")
        return self


class Caption(Interval):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=450)]


class NormalizedRegion(StrictModel):
    x: Unit
    y: Unit
    width: Unit
    height: Unit

    @model_validator(mode="after")
    def inside_frame(self):
        if min(self.width, self.height) <= 0 or max(self.x + self.width, self.y + self.height) > 1.0000001:
            raise ValueError("Region must fit inside the source frame")
        return self

    def pixels(self, media: audio.Media) -> Region:
        left, top = round(self.x * media.width), round(self.y * media.height)
        right = min(media.width, round((self.x + self.width) * media.width))
        bottom = min(media.height, round((self.y + self.height) * media.height))
        if right - left < 2 or bottom - top < 2:
            raise ValueError("Region must cover at least two pixels in both directions")
        return Region(x=left, y=top, width=right - left, height=bottom - top)


class EditDecision(StrictModel):
    start_seconds: Seconds
    end_seconds: Seconds
    cuts: list[Interval] = Field(default_factory=list, max_length=32)
    layout: RenderMode = "fit"
    track_id: int | None = Field(default=None, ge=1)
    roi: NormalizedRegion | None = None
    facecam: NormalizedRegion | None = None
    gameplay: NormalizedRegion | None = None
    subtitle_style: Literal["none", "standard", "word", "karaoke", "yellow", "gaming", "minimal"] = "standard"
    subtitle_position: Position = "bottom"
    subtitle_size: int = Field(default=52, ge=18, le=110)
    subtitle_font: str = Field(default="Arial", pattern=r"^[\w .-]{1,50}$")
    subtitle_color: Color = "#ffffff"
    highlight_color: Color = "#ffe477"
    subtitle_outline: int = Field(default=3, ge=0, le=12)
    subtitle_background: bool = False
    safe_margin: int = Field(default=140, ge=30, le=400)
    max_lines: Literal[1, 2, 3] = 2
    captions: list[Caption] | None = Field(default=None, max_length=1200)
    hook: str = Field(default="", max_length=120)
    hook_seconds: float = Field(default=3, ge=0.1, le=10, allow_inf_nan=False)
    hook_position: Position = "top"
    normalize_audio: bool = False
    denoise: bool = False
    fade_in: bool = False
    fps: Literal[24, 25, 30, 50, 60] = 30
    resolution: Literal[720, 1080] = 1080

    @model_validator(mode="after")
    def valid_edits(self):
        if not 0.25 <= self.end_seconds - self.start_seconds <= 180.001:
            raise ValueError("Select between 0.25 and 180 seconds of source video")
        cursor = self.start_seconds
        for cut in self.cuts:
            if cut.start < cursor or cut.end > self.end_seconds:
                raise ValueError("Cuts must be ordered, nonoverlapping and within the selection")
            cursor = cut.end
        if self.duration < 0.25:
            raise ValueError("At least 0.25 seconds must remain after cuts")
        if self.layout == "roi" and not self.roi:
            raise ValueError("Manual crop requires a source region")
        if self.layout in ("split", "split_below", "pip") and not self.facecam:
            raise ValueError("This layout requires a confirmed facecam region")
        if self.layout in TRACK_LAYOUTS and self.track_id is None:
            raise ValueError("Select a sampled face track for this layout")
        if self.captions and any(b.start < a.end for a, b in zip(self.captions, self.captions[1:])):
            raise ValueError("Manual captions must be ordered and cannot overlap")
        return self

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds - sum(s.end - s.start for s in self.cuts)

    def kept_spans(self) -> list[Interval]:
        start = self.start_seconds
        spans = []
        for cut in self.cuts:
            if cut.start > start:
                spans.append(Interval(start=start, end=cut.start))
            start = cut.end
        if start < self.end_seconds:
            spans.append(Interval(start=start, end=self.end_seconds))
        return spans


def default_decision(clip: Clip, request: JobRequest, media: audio.Media) -> EditDecision:
    def normalized(box: Region | None) -> NormalizedRegion | None:
        if box is None:
            return None
        return NormalizedRegion(x=box.x / media.width, y=box.y / media.height,
                                width=box.width / media.width, height=box.height / media.height)

    camera = clip.facecam_detection.region if clip.facecam_detection and clip.facecam_detection.region else request.facecam
    layout = clip.render_layout or request.layout or "fit"
    if layout == "auto_split":
        layout = "split" if camera else "fit"
    return EditDecision(start_seconds=clip.start_seconds, end_seconds=clip.end_seconds, layout=layout,
                        roi=normalized(request.roi), facecam=normalized(camera), gameplay=normalized(request.gameplay),
                        subtitle_style="standard" if request.subtitles else "none", subtitle_font=request.subtitle_font,
                        subtitle_position=request.subtitle_position, hook=clip.hook if request.opening_hook else "",
                        normalize_audio=request.normalize_audio, fade_in=request.fade_in)


@dataclass(frozen=True)
class TimedText:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Phrase:
    start: float
    end: float
    text: str
    words: tuple[TimedText, ...] = ()


def caption_timeline(edit: EditDecision, transcript: Transcript) -> list[Phrase]:
    """Map source speech onto the edited clock. A cut inside a word omits its word cue."""
    if edit.subtitle_style == "none":
        return []
    source = []
    if edit.captions is not None:
        source = [(c.start, c.end, c.text, False) for c in edit.captions]
    else:
        for segment in transcript.segments:
            if segment.start >= edit.end_seconds or segment.end <= edit.start_seconds:
                continue
            if segment.words:
                source.extend((w.start, w.end, w.text, True) for w in segment.words)
            elif segment.text.strip():
                source.append((segment.start, segment.end, segment.text, False))
    source.sort(key=lambda item: item[0])
    phrases = []
    offset = 0.0
    for span in edit.kept_spans():
        words = []

        def flush():
            if words:
                phrases.append(Phrase(words[0].start, words[-1].end, " ".join(w.text for w in words), tuple(words)))
                words.clear()

        for start, end, text, timed_word in source:
            if end <= span.start or start >= span.end or end <= start:
                continue
            text = " ".join(text.split())
            if not text or (timed_word and (start < span.start - 0.005 or end > span.end + 0.005)):
                continue
            begin = offset + max(span.start, start) - span.start
            stop = offset + min(span.end, end) - span.start
            if stop - begin < 0.01:
                continue
            if not timed_word:
                flush()
                phrases.append(Phrase(begin, stop, text))
                continue
            if words and (begin - words[-1].end > 0.42 or len(words) >= 5 or begin - words[0].start >= 2.4
                          or len(" ".join(w.text for w in words)) + len(text) >= 28 * edit.max_lines):
                flush()
            words.append(TimedText(begin, stop, text))
            if text.endswith((".", "!", "?")):
                flush()
        flush()
        offset += span.end - span.start
    return phrases


def _ass_color(rgb: str) -> str:
    return f"&H00{rgb[5:7]}{rgb[3:5]}{rgb[1:3]}".upper()


def _write_captions(folder: Path, edit: EditDecision, transcript: Transcript) -> bool:
    phrases = caption_timeline(edit, transcript)
    srt, vtt = [], ["WEBVTT\n"]
    positions = {"bottom": 2, "middle": 5, "top": 8}
    base = _ass_color(edit.subtitle_color)
    accent = _ass_color(edit.highlight_color)
    styled = edit.subtitle_style
    color = accent if styled in {"yellow", "gaming", "karaoke"} else base
    weight = 0 if styled == "minimal" else -1
    size = edit.subtitle_size
    outline = max(5, edit.subtitle_outline) if styled == "gaming" else edit.subtitle_outline
    style_format = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    def style(name: str, position: Position, primary: str, font_size: int) -> str:
        return (f"Style: {name},{edit.subtitle_font},{font_size},{primary},{base},&H00000000,&H70000000,"
                f"{weight},0,0,0,100,100,0,0,{3 if edit.subtitle_background else 1},{outline},1,"
                f"{positions[position]},70,70,{edit.safe_margin},1")

    ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 2",
           "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", style_format,
           style("Caption", edit.subtitle_position, color, size), style("Hook", edit.hook_position, accent, size + 6),
           "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    def event(start: float, end: float, text: str, *, hook: bool = False) -> None:
        a, b = stamp(start, ass=True), stamp(end, ass=True)
        if a != b:
            ass.append(f"Dialogue: {int(hook)},{a},{b},{'Hook' if hook else 'Caption'},,0,0,0,,{text}")

    def wrapped(text: str) -> list[str]:
        width = max(26, math.ceil(len(text) / edit.max_lines))
        lines = textwrap.wrap(text, width=width, break_on_hyphens=False) or [text]
        if len(lines) > edit.max_lines:
            return [*lines[:edit.max_lines - 1], " ".join(lines[edit.max_lines - 1:])]
        return lines

    for i, phrase in enumerate(phrases, 1):
        lines = wrapped(phrase.text)
        timing = f"{stamp(phrase.start)} --> {stamp(phrase.end)}"
        safe = "\n".join(lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        srt.append(f"{i}\n{timing}\n{safe}\n")
        vtt.append(f"{timing.replace(',', '.')}\n{safe}\n")
        if styled == "word" and phrase.words:
            for word in phrase.words:
                event(word.start, word.end, r"{\c" + accent + "&}" + ass_text(word.text))
        elif styled == "karaoke" and phrase.words:
            parts = []
            elapsed = 0
            for index, word in enumerate(phrase.words):
                start_tick = max(elapsed, round((word.start - phrase.start) * 100))
                end_tick = max(start_tick, round((word.end - phrase.start) * 100))
                # A timed space accounts for actual inter-word pauses.
                if index:
                    parts.append(r"{\k" + str(start_tick - elapsed) + "} ")
                parts.append(r"{\kf" + str(end_tick - start_tick) + "}" + ass_text(word.text))
                elapsed = end_tick
            event(phrase.start, phrase.end, "".join(parts))
        else:
            event(phrase.start, phrase.end, r"\N".join(ass_text(line) for line in lines))
    if edit.hook.strip():
        hook = " ".join(edit.hook.split())
        event(0, min(edit.duration, edit.hook_seconds), r"\N".join(ass_text(line) for line in wrapped(hook)), hook=True)
    for filename, lines in (("captions.srt", srt), ("captions.vtt", vtt), ("captions.ass", ass)):
        (folder / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bool(phrases or edit.hook.strip())


def _layout_graph(edit: EditDecision, media: audio.Media, width: int, height: int) -> str:
    def region(box: NormalizedRegion | None) -> str:
        return crop_region(box.pixels(media), media) + "," if box else ""

    def cover(w: int, h: int) -> str:
        return (f"scale={w}:{h}:force_original_aspect_ratio=increase:force_divisible_by=2,"
                f"crop={w}:{h},setsar=1")

    if edit.layout in {"split", "split_below"}:
        top = 2 * round(height * (650 / 1920) / 2)
        order = "[camera][game]" if edit.layout == "split" else "[game][camera]"
        return (f"[scene]split[facein][gamein];[facein]{region(edit.facecam)}{SQUARE_PIXELS},{fit(width, top)}[camera];"
                f"[gamein]{region(edit.gameplay)}{SQUARE_PIXELS},{fit(width, height - top)}[game];"
                f"{order}vstack[framed]")
    if edit.layout == "pip":
        w, h = 2 * round(width * 0.44 / 2), 2 * round(height * 0.23 / 2)
        return (f"[scene]split[facein][gamein];[facein]{region(edit.facecam)}{SQUARE_PIXELS},{fit(w, h)}[camera];"
                f"[gamein]{region(edit.gameplay)}{SQUARE_PIXELS},{fit(width, height)}[game];"
                "[game][camera]overlay=x=W-w-W*0.04:y=H*0.04[framed]")
    if edit.layout == "blur":
        return (f"[scene]{SQUARE_PIXELS},split[fore][back];[back]{cover(width, height)},boxblur=12:2[blurred];"
                f"[fore]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2[fit];"
                "[blurred][fit]overlay=(W-w)/2:(H-h)/2[framed]")
    return ("[scene]" + (region(edit.roi) if edit.layout == "roi" else "") + SQUARE_PIXELS + ","
            + (cover(width, height) if edit.layout == "crop" else fit(width, height)) + "[framed]")


def _framing(edit: EditDecision, media: audio.Media, width: int, height: int, track_points: list[dict]):
    if edit.layout not in TRACK_LAYOUTS:
        return _layout_graph(edit, media, width, height), edit.layout
    if media.sample_aspect_ratio in {"1:1","0:1","N/A"}:
        bounds = (media.width, media.height, edit.start_seconds, edit.end_seconds)
        if edit.layout == "track":
            crop = build_track_filter(track_points, *bounds)
            if crop:
                return f"[scene]{crop},{SQUARE_PIXELS},{fit(width,height)}[framed]", "track"
        else:
            dynamic = build_dynamic_filter(track_points, *bounds, width, height)
            if dynamic:
                return dynamic.replace("[trackin]", "[scene]").replace("[trackout]", "[framed]"), "dynamic"
    return _layout_graph(edit.model_copy(update={"layout":"fit"}), media, width, height), "fit"


def _render_graph(edit: EditDecision, media: audio.Media, framing: str, subtitles: bool) -> str:
    graph = [f"[0:{media.video_stream}]setpts=PTS-STARTPTS"]
    cuts = ""
    if edit.cuts:
        keep, removed = [], []
        for cut in edit.cuts:
            a, b = cut.start - edit.start_seconds, cut.end - edit.start_seconds
            keep.append(f"gte(t,{a:.9f})*lt(t,{b:.9f})")
            removed.append(f"{b-a:.9f}*gte(T,{b:.9f})")
        cuts = f"select='not({'+'.join(keep)})',setpts='PTS-({'+'.join(removed)})/TB'"
    source_clock = edit.layout in TRACK_LAYOUTS and cuts
    if cuts and not source_clock:
        graph[0] += "," + cuts
    graph[0] += "[scene]"
    graph.append(framing)
    video = "[framed]"
    if source_clock:
        graph.append(f"[framed]{cuts}[cutvideo]")
        video = "[cutvideo]"
    filters = [f"fps={edit.fps}", "setsar=1"]
    if edit.fade_in:
        filters.append("fade=t=in:st=0:d=0.2")
    if subtitles:
        filters.append("ass=captions.ass")
    # Supply at most two end frames to cover rounding between the two clocks.
    filters.append(f"tpad=stop_mode=clone:stop_duration={2/edit.fps:.6f}")
    graph.append(video + ",".join(filters) + "[outv]")
    if media.audio_streams:
        spans = edit.kept_spans()
        sample = f"[0:{media.audio_streams[0]}]aresample=48000:async=1:first_pts=0,apad"
        if len(spans) == 1:
            graph.append(sample + "[src0]")
        else:
            graph.append(sample + f",asplit={len(spans)}" + "".join(f"[src{i}]" for i in range(len(spans))))
        for i, span in enumerate(spans):
            start, end = span.start - edit.start_seconds, span.end - edit.start_seconds
            graph.append(f"[src{i}]atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS[part{i}]")
        graph.append("".join(f"[part{i}]" for i in range(len(spans))) + f"concat=n={len(spans)}:v=0:a=1[sound]")
    else:
        graph.append(f"anullsrc=sample_rate=48000:channel_layout=stereo,atrim=duration={edit.duration:.9f}[sound]")
    sound_filters = []
    if edit.denoise:
        sound_filters.append("afftdn=nf=-30")
    if edit.normalize_audio:
        sound_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    sound_filters.append("aresample=48000")
    graph.append("[sound]" + ",".join(sound_filters) + "[outa]")
    return ";".join(graph)


def _checksum(path: Path, cancel: Callable[[], None]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            cancel()
            digest.update(block)
    return digest.hexdigest()


def render_revision(settings: Settings, source: Path, transcript: Transcript, edit: EditDecision, directory: Path,
                    *, preview: bool, track_points: list[dict] | None = None,
                    cancel: Callable[[], None] = lambda: None) -> Path:
    """Publish a checked immutable revision. Call only for an authorized project on the media worker."""
    root = settings.root.resolve()
    source, directory = source.absolute(), directory.absolute()
    if (source.resolve() != source or not source.is_relative_to(root) or not source.is_file()
            or directory.resolve() != directory or not directory.is_relative_to(root) or directory == root):
        raise ValueError("Invalid source or render directory")
    if directory.is_relative_to(root / "input"):
        raise ValueError("Render destinations must be separate from original sources")
    media = audio.probe(settings, source, cancel)
    if edit.end_seconds > media.duration + 0.001:
        raise ValueError("Selection extends past the end of the source")
    width = 360 if preview else edit.resolution
    height = width * 16 // 9
    framing, resolved_layout = _framing(edit, media, width, height, track_points or [])
    # Retain cache compatibility for layout revisions written before track selection was added.
    key = hashlib.sha256(edit.model_dump_json(exclude={"track_id"} if edit.track_id is None else None).encode())
    for part in (str(preview), str(settings.crf), settings.ffmpeg_preset, _checksum(source, cancel),
                 transcript.model_dump_json(), "edit-render-v2.1"):
        key.update(b"\0" + part.encode())
    if edit.layout in TRACK_LAYOUTS:
        key.update(b"\0" + framing.encode())
    signature = key.hexdigest()
    directory.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory.with_name("." + directory.name + ".lock")), timeout=1):
        cancel()
        if directory.exists():
            report = directory / "report.json"
            if report.is_symlink() or not report.is_file():
                raise FileExistsError("The destination already exists without a checked render")
            record = json.loads(report.read_bytes())
            files = ("clip.mp4", "captions.srt", "captions.vtt", "captions.ass", "edit.json")
            if record.get("signature") != signature:
                raise FileExistsError("This render revision belongs to different source or edit settings")
            for name in files:
                path = directory / name
                if path.is_symlink() or not path.is_file() or _checksum(path, cancel) != record["checksums"].get(name):
                    raise ValueError("A saved render artifact failed its integrity check")
            return directory / "clip.mp4"
        if shutil.disk_usage(directory.parent).free < settings.minimum_free_bytes:
            raise ValueError("Free disk space is below the configured render limit")
        with TemporaryDirectory(dir=directory.parent, prefix=".render-") as temp:
            folder = Path(temp) / "result"
            folder.mkdir()
            target = folder / "clip.mp4"
            write_json(folder / "edit.json", edit)
            captions = _write_captions(folder, edit, transcript)
            graph = _render_graph(edit, media, framing, captions)
            run([settings.executable("ffmpeg"), "-nostdin", "-v", "error", "-xerror", "-n",
                 "-protocol_whitelist", "file", "-f", audio.input_format(source),
                 "-ss", f"{edit.start_seconds:.9f}", "-t", f"{edit.end_seconds-edit.start_seconds:.9f}",
                 "-threads", str(settings.cpu_threads), "-i", str(source), "-filter_complex_threads",
                 str(settings.cpu_threads), "-filter_complex", graph, "-map", "[outv]", "-map", "[outa]",
                 "-t", f"{edit.duration:.9f}", "-map_metadata", "-1", "-map_chapters", "-1",
                 "-c:v", "libx264", "-threads:v", str(settings.cpu_threads), "-pix_fmt", "yuv420p",
                 "-preset", "ultrafast" if preview else settings.ffmpeg_preset,
                 "-crf", str(27 if preview else settings.crf), "-c:a", "aac",
                 "-b:a", "96k" if preview else "160k", "-movflags", "+faststart", str(target)],
                cwd=folder, check_cancel=cancel, timeout=settings.ffmpeg_timeout)
            measured = audio.probe(settings, target, cancel)
            if ((measured.width, measured.height) != (width, height)
                    or measured.video_codec != "h264" or "aac" not in measured.audio_codecs
                    or measured.pixel_format != "yuv420p" or measured.sample_aspect_ratio != "1:1"
                    or abs(measured.duration - edit.duration) > max(0.08, 1.5/edit.fps)
                    or abs(measured.fps - edit.fps) > 0.1):
                raise ValueError("Rendered output failed its format or duration checks")
            run([settings.executable("ffmpeg"), "-nostdin", "-v", "error", "-xerror", "-protocol_whitelist", "file",
                 "-threads", str(settings.cpu_threads), "-i", str(target), "-map", "0:v:0", "-map", "0:a:0",
                 "-f", "null", "-"], cwd=folder, timeout=settings.ffmpeg_timeout, check_cancel=cancel)
            checksums = {p.name: _checksum(p, cancel) for p in folder.iterdir()}
            write_json(folder / "report.json", {"signature": signature, "checksums": checksums,
                                                "duration": measured.duration, "width": width, "height": height,
                                                "fps": measured.fps, "kind": "preview" if preview else "final",
                                                "requested_layout": edit.layout, "rendered_layout": resolved_layout})
            cancel()
            folder.rename(directory)
    return directory / "clip.mp4"
