from app.config import Settings
from app.schemas import ProcessingPreset


def processing_settings(settings: Settings, preset: ProcessingPreset | None) -> Settings:
    if preset == "fast":
        return settings.model_copy(update={
            "visual_sample_seconds": min(60, settings.visual_sample_seconds * 2),
            "visual_max_samples": max(12, settings.visual_max_samples // 2),
            "whisper_beam_size": 1,
            "ffmpeg_preset": "ultrafast",
            "crf": max(25, settings.crf),
        })
    if preset == "quality":
        return settings.model_copy(update={
            "visual_sample_seconds": max(0.25, settings.visual_sample_seconds / 2),
            "visual_max_samples": min(1800, settings.visual_max_samples * 2),
            "whisper_beam_size": max(5, settings.whisper_beam_size),
            "ffmpeg_preset": "medium",
            "crf": min(18, settings.crf),
        })
    return settings
