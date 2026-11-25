import logging
import os
import shutil
import threading
import time
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.database import Database
from app.schemas import Campaign, Clip, Job, Region, SignalEvent, Status, Transcript
from app.services import audio, clip_selector, clip_validator, facecam, subtitles, video_editor
from app.services.campaigns import load_campaign, resolve_request
from app.services.metadata import export_metadata
from app.services.quality_checker import MANUAL_REVIEW, quality_check
from app.services.transcription import Transcriber, cache_key, cached_transcript
from app.utils.files import child, source_path, write_json
from app.utils.process import Cancelled
from app.v2.presets import processing_settings

log = logging.getLogger("momentrix.worker")


class Worker:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.stop = threading.Event()
        self.studio_enabled = False
        self.wake = threading.Event()
        self.transcriber = Transcriber(settings)
        self.thread = threading.Thread(target=self.loop, name="momentrix-worker", daemon=True)

    def loop(self) -> None:
        from app.v2.tasks import run_next
        while not self.stop.is_set():
            if self.studio_enabled and run_next(self):
                continue
            job = self.database.claim()
            if job is None:
                self.wake.wait(1)
                self.wake.clear()
                continue
            try:
                self.process(job)
            except Cancelled:
                if not self.stop.is_set():
                    self.database.finish(job.job_id, Status.CANCELLED)
            except (ValueError, OSError, RuntimeError) as exc:
                log.warning("job_failed job_id=%s error_type=%s", job.job_id, type(exc).__name__)
                self.database.finish(job.job_id, Status.FAILED, error=str(exc))
            except Exception as exc:
                log.error("job_failed job_id=%s error_type=%s", job.job_id, type(exc).__name__)
                self.database.finish(job.job_id, Status.FAILED,
                                     error=f"Unexpected processing error ({type(exc).__name__})")
            finally:
                self.transcriber.release()

    def process(self, job: Job) -> None:
        settings = self.settings
        with self.database.transaction() as conn:
            studio = conn.execute("SELECT 1 FROM sqlite_master WHERE name='runs'").fetchone()
            v2 = conn.execute("SELECT asset_id,campaign FROM runs WHERE job_id=? AND campaign IS NOT NULL",
                              (job.job_id,)).fetchone() if studio else None
        campaign = (Campaign.model_validate_json(v2["campaign"]) if v2
                    else load_campaign(settings.root, job.request.campaign))
        request = resolve_request(job.request, campaign)
        preset = request.processing_preset if v2 else None
        settings = processing_settings(settings, preset)
        transcriber = self.transcriber if settings is self.settings else Transcriber(settings)
        if preset:
            request = request.model_copy(update={"quality": "standard"})
        source = source_path(settings.root / "input", request.filename, settings.max_input_bytes)
        output = child(settings.root / "output", job.job_id)
        output.mkdir()
        warnings = []
        clips: list[Clip] = []
        report = {"source_filename": source.name, "campaign": campaign.name, "requested_clips": request.count,
                  "selection_mode": "ollama", "ollama_model": settings.ollama_model,
                  "requested_layout": request.layout,
                  "source_authorization_attested": request.authorized,
                  "manual_review": [*MANUAL_REVIEW, *campaign.manual_review]}
        if v2:
            report.update(processing_preset=preset or "balanced", whisper_beam_size=settings.whisper_beam_size,
                          ffmpeg_preset="ultrafast" if request.quality == "low" else settings.ffmpeg_preset)
        stage_started = started = time.monotonic()
        stage_name = Status.PROBING
        stage_times: dict[str, float] = defaultdict(float)
        last_progress = 0
        status = Status.FAILED
        checked_at = 0.0

        def cancel() -> None:
            nonlocal checked_at
            if self.stop.is_set():
                raise Cancelled("Job cancelled or backend shutting down")
            now = time.monotonic()
            if now - checked_at >= 0.2:
                checked_at = now
                if self.database.get(job.job_id).cancel_requested:
                    raise Cancelled("Job cancellation requested")

        def stage(name: Status, progress: int) -> None:
            nonlocal stage_started, stage_name, last_progress
            cancel()
            changed = name != stage_name
            if changed:
                now = time.monotonic()
                stage_times[stage_name.value] += now - stage_started
                stage_started, stage_name = now, name
                log.info("job_stage job_id=%s stage=%s", job.job_id, name)
            if changed or progress > last_progress:
                self.database.advance(job.job_id, name, progress)
                last_progress = progress

        try:
            self.database.advance(job.job_id, Status.PROBING, 3, output=f"output/{job.job_id}")
            media = audio.probe(settings, source, cancel)
            report["source_duration"] = media.duration
            report["source_video_codec"] = media.video_codec
            report["source_resolution"] = [media.width, media.height]
            report["source_aspect_ratio"] = media.aspect_ratio
            report["source_fps"] = media.fps
            report["source_audio_codecs"] = media.audio_codecs
            if media.duration > settings.max_source_seconds:
                raise ValueError("Source duration exceeds the configured limit")
            free = shutil.disk_usage(settings.root).free
            if free < settings.minimum_free_bytes + int(media.duration * 32_000):
                raise ValueError("Free disk space is below the limit for this source")
            with TemporaryDirectory(prefix=f"{job.job_id}-", dir=settings.root / "cache") as temp:
                staging = Path(temp)
                if not media.audio_streams:
                    transcript = Transcript(source_filename=source.name, source_duration=media.duration,
                                            language=None, segments=[])
                    warnings.append("The source has no audio stream.")
                else:
                    stage(Status.AUDIO, 8)
                    key = cache_key(settings, source, cancel)
                    transcript = cached_transcript(key, source)
                    report["transcript_cache_hit"] = transcript is not None
                    if transcript is None:
                        wav = staging / "source.wav"
                        audio.extract(settings, source, media.audio_streams[0], wav, cancel)
                        stage(Status.TRANSCRIBING, 15)
                        try:
                            transcript = transcriber.transcribe(
                                wav, source, media.duration, cancel,
                                lambda fraction: stage(Status.TRANSCRIBING, 15 + int(fraction * 28)),
                            )
                        finally:
                            transcriber.release()
                        write_json(key, transcript)
                        wav.unlink()
                write_json(output / "transcript.json", transcript)

                rank_options = {}
                selection_options = {}
                if v2:
                    from app.v2.analysis import signal_candidates, speech_features
                    from app.v2.media_assets import prepare_asset
                    stage(Status.ANALYZING, 44)
                    manifest = prepare_asset(self.settings, self.database, v2["asset_id"], cancel,
                                             preset=preset or "balanced")
                    events = [SignalEvent.model_validate(row) for row in manifest["events"]]
                    events += speech_features(transcript)
                    report.update(selection_mode="multimodal", visual_sample_count=manifest["sample_count"],
                                  analysis_event_count=len(events), ranking_weights=settings.rank_weights,
                                  analysis_stage_seconds=manifest["stage_seconds"],
                                  visual_sample_interval=manifest["sample_interval"])
                    write_json(output / "analysis_events.json", [row.model_dump() for row in events])
                    rank_options = {"events": events, "weights": settings.rank_weights,
                                    "audio_available": manifest["audio_available"],
                                    "visual_available": manifest["sample_count"] > 1}
                    selection_options["events"] = events
                stage(Status.SELECTING, 45)
                candidates = []
                if not transcript.segments:
                    if media.audio_streams:
                        warnings.append("No speech was detected in the source.")
                    if v2 and not campaign.language:
                        candidates = signal_candidates(events, media.duration, request.min_duration,
                                                       request.max_duration, campaign.preferred_min,
                                                       request.count * 3)
                    elif v2 and campaign.language:
                        warnings.append("A spoken-language requirement could not be verified without dialogue.")
                elif campaign.language and campaign.language != transcript.language:
                    warnings.append(f"Detected language {transcript.language} does not meet campaign language {campaign.language}.")
                else:
                    if settings.whisper_model.endswith(".en") and campaign.language:
                        warnings.append("English-only Whisper forces English. Verify the original language manually.")
                    candidates = clip_selector.select(
                        settings, transcript, campaign, request.min_duration, request.max_duration,
                        request.count, cancel,
                        lambda fraction: stage(Status.SELECTING, 45 + int(fraction * 16)),
                        **selection_options,
                    )
                    if not candidates:
                        warnings.append("No transcript window produced a highlight for the campaign and duration range.")
                write_json(output / "candidates.json", [
                    {**candidate.model_dump(mode="json"), "window": [window.start, window.end]}
                    for candidate, window in candidates
                ])

                stage(Status.VALIDATING, 63)
                ranked = clip_validator.rank(
                    candidates, transcript, campaign, request.min_duration, request.max_duration, request.count,
                    **rank_options,
                )
                selected, rejected = ranked.clips, ranked.rejections
                report["candidate_count"], report["rejected_candidates"] = len(candidates), rejected
                if ranked.campaign_issues:
                    report["campaign_rejections"] = ranked.campaign_issues
                if len(selected) < request.count and rejected:
                    summary = ", ".join(f"{reason} ({number})" for reason, number in rejected.items())
                    warnings.append(f"Candidates rejected for {summary}.")
                    for reason, number in ranked.campaign_issues.items():
                        noun = "candidate" if number == 1 else "candidates"
                        warnings.append(f"{reason} in {number} {noun}.")
                    log.warning("clip_selection_shortfall job_id=%s accepted=%d requested=%d rejections=%s",
                                job.job_id, len(selected), request.count, rejected)
                if request.layout == "roi":
                    video_editor.crop_region(request.roi, media)
                if request.layout == "split":
                    video_editor.crop_region(request.facecam, media)
                if request.layout in {"split", "auto_split"} and request.gameplay is not None:
                    video_editor.crop_region(request.gameplay, media)
                for index, candidate in enumerate(selected, 1):
                    clip_id = f"clip_{index:02d}"
                    if shutil.disk_usage(settings.root).free < settings.minimum_free_bytes:
                        warnings.append("Rendering stopped because free disk space fell below the configured limit.")
                        break
                    progress = 65 + (index - 1) * 30 // len(selected)
                    stage(Status.RENDERING, progress)
                    try:
                        render_request = request
                        detection = None
                        if request.layout == "auto_split":
                            try:
                                detection = facecam.detect(settings, source, media, candidate, staging, cancel)
                            except Cancelled:
                                raise
                            except (OSError, RuntimeError) as exc:
                                log.warning("facecam_unavailable job_id=%s clip_id=%s error_type=%s",
                                            job.job_id, clip_id, type(exc).__name__)
                            if detection is not None and detection.region is not None:
                                gameplay = request.gameplay or Region(x=0, y=0, width=media.width, height=media.height)
                                render_request = request.model_copy(update={
                                    "layout": "split", "facecam": detection.region, "gameplay": gameplay,
                                })
                            else:
                                reason = ("Facecam analysis was unavailable" if detection is None
                                          else "No stable corner facecam was detected")
                                warnings.append(f"{clip_id}: {reason}. Used Fit layout.")
                                render_request = request.model_copy(update={"layout": "fit"})
                        phrases = subtitles.cues(transcript, candidate.start_seconds, candidate.end_seconds) if request.subtitles else []
                        srt, ass = subtitles.write_subtitles(staging, clip_id, candidate, request, phrases)
                        filename = f"{clip_id}.mp4"
                        video_editor.render(settings, source, staging / filename, media, candidate, render_request,
                                            ass, cancel)
                        stage(Status.CHECKING, progress + 1)
                        checks = quality_check(settings, staging / filename, candidate, request, campaign, phrases, cancel)
                    except Cancelled:
                        raise
                    except (ValueError, OSError, RuntimeError) as exc:
                        warnings.append(f"{clip_id} could not be exported. {exc}")
                        continue
                    for name in (filename, srt, ass):
                        if name:
                            os.replace(staging / name, output / name)
                    if request.subtitles and not phrases:
                        warnings.append(f"{clip_id} had no usable word timings for subtitles.")
                    clips.append(Clip(**candidate.model_dump(), clip_id=clip_id, file=filename,
                                      subtitle_file=srt, duration=candidate.end_seconds - candidate.start_seconds,
                                      technical_checks=checks, manual_review=report["manual_review"],
                                      hook_burned=request.opening_hook, render_layout=render_request.layout,
                                      facecam_detection=detection))
            if len(clips) < request.count:
                noun = "candidate" if len(selected) == 1 else "candidates"
                warnings.append(f"Exported {len(clips)} of {request.count} requested clips. "
                                f"Validation kept {len(selected)} {noun}.")
            if selected and not clips:
                raise RuntimeError("All selected clips failed to export. Check the job report.")
            cancel()
            status = Status.WARNINGS if warnings else Status.COMPLETED
        except Cancelled:
            status = Status.CANCELLED
            raise
        except (ValueError, OSError, RuntimeError) as exc:
            report["error"] = str(exc)
            raise
        finally:
            stage_times[stage_name.value] += time.monotonic() - stage_started
            report.update(status=status.value, warnings=warnings, exported_clips=len(clips),
                          elapsed_seconds=round(time.monotonic() - started, 2),
                          stage_seconds={name: round(seconds, 2) for name, seconds in stage_times.items()})
            export_metadata(output, clips)
            write_json(output / "job_report.json", report)
            self.database.advance(job.job_id, stage_name, last_progress, warnings=warnings)
        self.database.finish(job.job_id, status)
