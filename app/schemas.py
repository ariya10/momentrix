from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Hashtag = Annotated[str, StringConstraints(pattern=r"^#[^\W#]+$", max_length=80)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Duration = Annotated[float, Field(ge=3, le=180, allow_inf_nan=False)]
RenderLayout = Literal["fit", "crop", "roi", "split"]
Layout = Literal[RenderLayout, "auto_split"]
ProcessingPreset = Literal["fast", "balanced", "quality"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Region(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=2)
    height: int = Field(ge=2)


class FacecamDetection(StrictModel):
    region: Region | None
    sampled_frames: int = Field(ge=0)
    matching_frames: int = Field(ge=0)


class JobRequest(StrictModel):
    filename: str = Field(min_length=1, max_length=240)
    campaign: str = Field(default="default", pattern=r"^[a-z0-9_]+$", max_length=48)
    count: int | None = Field(default=None, ge=1, le=20)
    layout: Layout | None = None
    min_duration: Duration | None = None
    max_duration: Duration | None = None
    subtitles: bool = True
    subtitle_font: str = Field(default="Arial", pattern=r"^[\w .-]{1,50}$")
    subtitle_position: Literal["bottom", "middle", "top"] = "bottom"
    opening_hook: bool = False
    normalize_audio: bool = False
    fade_in: bool = False
    quality: Literal["standard", "low"] = "standard"
    processing_preset: ProcessingPreset | None = None
    authorized: bool = False
    roi: Region | None = None
    facecam: Region | None = None
    gameplay: Region | None = None

    @model_validator(mode="after")
    def required_regions(self):
        if self.layout == "roi" and self.roi is None:
            raise ValueError("ROI layout requires roi coordinates")
        if self.layout == "split" and (self.facecam is None or self.gameplay is None):
            raise ValueError("Split layout requires facecam and gameplay coordinates")
        return self


class Campaign(StrictModel):
    name: ShortText
    creator: str = ""
    category: ShortText
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    min_duration: Duration = 20
    max_duration: Duration = 60
    count: int = Field(default=10, ge=1, le=20)
    preferred_min: Duration = 30
    preferred_max: Duration = 45
    required_keywords: list[ShortText] = Field(default_factory=list, max_length=20)
    required_hashtags: list[Hashtag] = Field(default_factory=list, max_length=20)
    hook_requires: list[ShortText] = Field(default_factory=list, max_length=10)
    caption_requires: list[ShortText] = Field(default_factory=list, max_length=10)
    prohibited_content: list[ShortText] = Field(default_factory=list, max_length=20)
    layout: Literal["fit", "crop", "auto_split"] = "fit"
    authorization_required: bool = True
    manual_review: list[ShortText] = Field(default_factory=list, max_length=20)
    allow_added_branding: Literal[False] = False

    @model_validator(mode="after")
    def ranges(self):
        if self.min_duration > self.max_duration or self.preferred_min > self.preferred_max:
            raise ValueError("Campaign duration ranges must be ordered")
        return self


class Word(StrictModel):
    start: Seconds
    end: Seconds
    text: str


class Segment(Word):
    words: list[Word] = Field(default_factory=list)


class Transcript(StrictModel):
    source_filename: str
    source_duration: Seconds
    language: str | None
    segments: list[Segment]


class Scores(StrictModel):
    hook: int = Field(ge=0, le=25)
    entertainment: int = Field(ge=0, le=25)
    standalone: int = Field(ge=0, le=20)
    payoff: int = Field(ge=0, le=15)
    relevance: int = Field(ge=0, le=15)

    @property
    def total(self) -> int:
        return self.hook + self.entertainment + self.standalone + self.payoff + self.relevance


class Metadata(StrictModel):
    hook: ShortText
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    caption: str = Field(min_length=1, max_length=600)
    description: str = Field(min_length=1, max_length=800)
    hashtags: list[Hashtag] = Field(max_length=20)


class PublishingMetadata(Metadata):
    instagram_caption: str = Field(default="", max_length=600)
    tiktok_caption: str = Field(default="", max_length=600)
    thumbnail_text: str = Field(default="", max_length=80)


class Highlight(Metadata):
    category: ShortText
    score: int = Field(ge=0, le=100)
    score_breakdown: Scores
    selection_reason: str = Field(min_length=1, max_length=500)
    supporting_transcript: str = Field(min_length=1, max_length=1000)
    review_flags: list[ShortText] = Field(max_length=12)


class Candidate(Highlight):
    start_seconds: Seconds
    end_seconds: Seconds


class MeasuredCandidate(Candidate):
    supporting_transcript: str = Field(max_length=1000)
    evidence_mode: Literal["dialogue", "signal"] = "dialogue"
    component_scores: dict[str, Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=dict)
    evidence: list["SignalEvent"] = Field(default_factory=list, max_length=16)
    confidence: float | None = Field(default=None, ge=0, le=1)


class SignalEvent(StrictModel):
    start: Seconds
    end: Seconds
    signal: Literal["audio_peak", "audio_rise", "scene_change", "motion", "silence", "speech_rate"]
    strength: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    detail: str = Field(min_length=1, max_length=350)


class ProposedHighlight(Highlight):
    range_id: int = Field(ge=0)


class Proposal(StrictModel):
    clips: list[ProposedHighlight] = Field(max_length=6)


ReviewState = Literal["pending", "approved", "rejected"]


class Review(StrictModel):
    status: ReviewState
    note: str = Field(default="", max_length=1500)


class Clip(MeasuredCandidate):
    clip_id: str
    file: str
    duration: Seconds
    subtitle_file: str | None = None
    review: Review = Field(default_factory=lambda: Review(status="pending"))
    technical_checks: list[str]
    manual_review: list[str]
    hook_burned: bool = False
    render_layout: RenderLayout | None = None
    facecam_detection: FacecamDetection | None = None


class Status(StrEnum):
    QUEUED = "queued"
    PROBING = "probing"
    AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing_media"
    SELECTING = "selecting"
    VALIDATING = "validating"
    RENDERING = "rendering"
    CHECKING = "quality_checking"
    COMPLETED = "completed"
    WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {Status.COMPLETED, Status.WARNINGS, Status.FAILED, Status.CANCELLED}


class Job(StrictModel):
    job_id: str
    request: JobRequest
    status: Status
    progress: int = Field(ge=0, le=100)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    output: str | None = None
    cancel_requested: bool = False


class SystemStatus(StrictModel):
    ffmpeg: bool
    ffprobe: bool
    whisper_installed: bool
    whisper_model_available: bool
    whisper_model: str
    ollama: bool
    ollama_model_available: bool
    ollama_model: str
    free_disk_bytes: int
