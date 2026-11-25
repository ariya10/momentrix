import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

from app.config import Settings
from app.utils.process import run


@dataclass(frozen=True)
class Media:
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    pixel_format: str
    sample_aspect_ratio: str
    rotation: int
    video_stream: int
    audio_streams: tuple[int, ...]
    audio_codecs: tuple[str, ...]

    @property
    def aspect_ratio(self) -> str:
        ratio = Fraction(self.width, self.height)
        try:
            sar = Fraction(self.sample_aspect_ratio.replace(":", "/"))
            if sar > 0:
                ratio *= 1 / sar if self.rotation % 180 else sar
        except (ValueError, ZeroDivisionError):
            pass
        return f"{ratio.numerator}:{ratio.denominator}"


def input_format(path: Path) -> str:
    return "mov" if path.suffix.lower() in {".mp4", ".mov"} else "matroska"


def probe(settings: Settings, path: Path, cancel: Callable[[], None]) -> Media:
    try:
        payload = json.loads(run([
            settings.executable("ffprobe"), "-v", "error", "-protocol_whitelist", "file",
            "-f", input_format(path), "-show_streams", "-show_format", "-of", "json", str(path),
        ], check_cancel=cancel, timeout=45, cwd=settings.root / "cache"))
        video = next(s for s in payload["streams"]
                     if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic"))
        audio = [s for s in payload["streams"] if s["codec_type"] == "audio"]
        duration = float(payload["format"]["duration"])
        width, height = int(video["width"]), int(video["height"])
        rate = video.get("avg_frame_rate", "0/0")
        if rate in ("0/0", "0"):
            rate = video.get("r_frame_rate", "0")
        fps = float(Fraction(rate)) if rate != "0/0" else 0.0
        if not math.isfinite(duration) or duration <= 0 or min(width, height) <= 0:
            raise ValueError("Invalid media dimensions or duration")
        rotation = next((round(s["rotation"]) for s in video.get("side_data_list", [])
                         if "rotation" in s), 0)
        if rotation % 180:
            width, height = height, width
        return Media(duration, width, height, fps, video["codec_name"], video.get("pix_fmt", ""),
                     video.get("sample_aspect_ratio", "1:1"), rotation, video["index"],
                     tuple(s["index"] for s in audio), tuple(s["codec_name"] for s in audio))
    except (KeyError, ValueError, ZeroDivisionError, StopIteration) as exc:
        raise ValueError("The file has no valid video stream or readable media duration") from exc


def extract(settings: Settings, source: Path, stream: int, target: Path,
            cancel: Callable[[], None]) -> None:
    run([settings.executable("ffmpeg"), "-v", "error", "-xerror", "-nostdin", "-n",
         "-protocol_whitelist", "file", "-f", input_format(source), "-i", str(source), "-map", f"0:{stream}",
         "-af", "aresample=async=1:first_pts=0", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(target)],
        timeout=settings.ffmpeg_timeout, check_cancel=cancel, cwd=target.parent)
