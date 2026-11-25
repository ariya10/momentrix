from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOMENTRIX_", env_file=ROOT / ".env", extra="ignore"
    )

    root: Path = ROOT
    api_token: str = Field(default="", repr=False)
    webhook_secret: str = Field(default="", repr=False)
    service_token: str = Field(default="", repr=False)
    n8n_url: HttpUrl = HttpUrl("http://127.0.0.1:5678")
    scheduled_filenames: list[str] = Field(default_factory=list, max_length=100)
    scheduled_auto_process: bool = False
    scheduled_campaign: str = "default"
    visual_sample_seconds: float = Field(default=1.5, ge=0.25, le=60)
    visual_max_samples: int = Field(default=360, ge=12, le=1800)
    rank_weights: dict[str, float] = Field(default_factory=lambda: {
        "hook": 20, "entertainment": 20, "audio": 15, "visual": 15,
        "standalone": 15, "payoff": 10, "relevance": 5})
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    whisper_model: str = "base.en"
    whisper_device: Literal["cpu", "cuda"] = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = Field(default=3, ge=1, le=10)
    cpu_threads: int = Field(default=4, ge=1, le=32)
    ollama_url: HttpUrl = HttpUrl("http://localhost:11434")
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout: float = Field(default=180, ge=1)
    ollama_attempts: int = Field(default=2, ge=1, le=4)
    max_input_bytes: int = Field(default=12 * 1024**3, gt=0)
    max_source_seconds: int = Field(default=4 * 3600, gt=0)
    minimum_free_bytes: int = Field(default=512 * 1024**2, ge=0)
    ffmpeg_timeout: int = Field(default=1800, gt=0)
    fps: int = Field(default=30, ge=15, le=60)
    crf: int = Field(default=21, ge=15, le=35)
    ffmpeg_preset: Literal["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"] = "veryfast"

    @field_validator("api_token", "webhook_secret", "service_token")
    @classmethod
    def header_safe_token(cls, value: str) -> str:
        if value and (len(value) < 24 or not value.isascii() or any(c.isspace() for c in value)):
            raise ValueError("API token must contain at least 24 ASCII characters without whitespace")
        return value

    @field_validator("rank_weights")
    @classmethod
    def usable_rank_weights(cls, value: dict[str, float]) -> dict[str, float]:
        import math
        supported = {"hook", "entertainment", "audio", "visual", "standalone", "payoff", "relevance"}
        if set(value) - supported or not any(weight > 0 for weight in value.values()):
            raise ValueError("Provide positive weights for at least one supported component")
        if any(not math.isfinite(weight) or weight < 0 for weight in value.values()):
            raise ValueError("Scoring weights must be finite and nonnegative")
        return value

    @field_validator("ollama_url", "n8n_url")
    @classmethod
    def local_ollama(cls, value: HttpUrl) -> HttpUrl:
        if value.host not in {"localhost", "127.0.0.1", "[::1]"} or value.username or value.password:
            raise ValueError("The service must run on the local host")
        return value

    @field_validator("ollama_model")
    @classmethod
    def local_model_name(cls, value: str) -> str:
        tag = value.rsplit("/", 1)[-1].casefold()
        if "://" in value or tag.endswith((":cloud", "-cloud")):
            raise ValueError("Select an installed local Ollama model")
        return value

    @property
    def ollama_base(self) -> str:
        return str(self.ollama_url).rstrip("/")

    def prepare(self) -> None:
        for name in ("input", "output", "cache", "logs", "data", "storage"):
            folder = self.root / name
            if folder.is_symlink() or folder.resolve() != self.root.resolve() / name:
                raise ValueError(f"Project storage {name}/ cannot point outside its configured path")
            folder.mkdir(parents=True, exist_ok=True)

    def executable(self, name: Literal["ffmpeg", "ffprobe"]) -> str:
        configured = getattr(self, name)
        if configured != name:
            path = Path(configured)
            return str((self.root / path).resolve()) if not path.is_absolute() else str(path)
        portable = sorted((self.root / "cache" / "tools").glob(f"*/bin/{name}.exe"), reverse=True)
        return str(portable[0]) if portable else name
