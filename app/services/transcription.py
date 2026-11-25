import hashlib
import json
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.schemas import Segment, Transcript, Word
from app.utils.files import write_json


def model_location(settings: Settings, *, local_only: bool = True) -> str:
    from faster_whisper.utils import download_model

    configured = Path(settings.whisper_model)
    model_path = configured if configured.is_absolute() else settings.root / configured
    if (model_path / "model.bin").is_file():
        return str(model_path)
    return download_model(settings.whisper_model, cache_dir=str(settings.root / "cache" / "models"),
                          local_files_only=local_only)


def cache_key(settings: Settings, source: Path, cancel: Callable[[], None]) -> Path:
    signature = [settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
                 version("faster-whisper"), "vad+word-timestamps-v1"]
    if settings.whisper_beam_size != 3:
        signature.append(settings.whisper_beam_size)
    local_model = settings.root / settings.whisper_model / "model.bin"
    if local_model.is_file():
        details = local_model.stat()
        signature.extend([details.st_size, details.st_mtime_ns])
    digest = hashlib.sha256(json.dumps(signature).encode())
    with source.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            cancel()
            digest.update(block)
    return settings.root / "cache" / f"{digest.hexdigest()}.json"


def cached_transcript(path: Path, source: Path) -> Transcript | None:
    try:
        result = Transcript.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):
        return None
    return result.model_copy(update={"source_filename": source.name})


class Transcriber:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None

    def transcribe(self, audio: Path, source: Path, duration: float,
                   cancel: Callable[[], None], progress: Callable[[float], None]) -> Transcript:
        from faster_whisper import WhisperModel

        if self.model is None:
            try:
                location = model_location(self.settings)
            except (OSError, ValueError) as exc:
                raise RuntimeError("Whisper model is unavailable locally. Run scripts/download_whisper.ps1.") from exc
            self.model = WhisperModel(location, device=self.settings.whisper_device,
                                      compute_type=self.settings.whisper_compute_type,
                                      cpu_threads=self.settings.cpu_threads, local_files_only=True)
        language = "en" if self.settings.whisper_model.endswith(".en") else None
        segments, info = self.model.transcribe(audio.as_posix(), language=language,
                                               vad_filter=True, word_timestamps=True,
                                               beam_size=self.settings.whisper_beam_size)
        result = Transcript(source_filename=source.name, source_duration=duration,
                            language=info.language, segments=[])
        for segment in segments:
            cancel()
            start, end = max(0, segment.start), min(duration, segment.end)
            if end <= start or not segment.text.strip():
                continue
            words = [Word(start=max(0, w.start), end=min(duration, w.end), text=w.word)
                     for w in segment.words or () if min(duration, w.end) > max(0, w.start)]
            result.segments.append(Segment(start=start, end=end, text=segment.text.strip(), words=words))
            progress(min(1.0, end / duration))
        cancel()
        return result

    def release(self) -> None:
        self.model = None
