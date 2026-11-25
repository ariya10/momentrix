from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.schemas import Candidate, JobRequest, Region
from app.services.audio import Media, input_format
from app.utils.process import run

WIDTH, HEIGHT = 1080, 1920
SQUARE_PIXELS = "scale=w='max(2,trunc(iw*if(gt(sar,0),sar,1)/2)*2)':h=ih,setsar=1"


def crop_region(region: Region, media: Media) -> str:
    if region.x + region.width > media.width or region.y + region.height > media.height:
        raise ValueError("Crop region extends outside the decoded video frame")
    return f"crop={region.width}:{region.height}:{region.x}:{region.y}:exact=1"


def fit(width: int, height: int) -> str:
    return (f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def graph(request: JobRequest, media: Media, fps: int, ass_name: str | None) -> str:
    if request.layout == "auto_split":
        raise ValueError("Automatic facecam layout must be resolved before rendering")
    source = f"0:{media.video_stream}"
    if request.layout == "split":
        face = crop_region(request.facecam, media)
        game = crop_region(request.gameplay, media)
        layout = (f"[{source}]split=2[f][g];[f]{face},{SQUARE_PIXELS},{fit(WIDTH, 650)}[face];"
                  f"[g]{game},{SQUARE_PIXELS},{fit(WIDTH, HEIGHT - 650)}[game];"
                  "[face][game]vstack=inputs=2")
    else:
        start = f"[{source}]"
        if request.layout == "roi":
            start += crop_region(request.roi, media) + ","
        if request.layout == "crop":
            output = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:force_divisible_by=2,"
                      f"crop={WIDTH}:{HEIGHT},setsar=1")
        else:
            output = fit(WIDTH, HEIGHT)
        layout = f"{start}{SQUARE_PIXELS},{output}"
    filters = f"{layout},fps={fps}"
    if request.fade_in:
        filters += ",fade=t=in:st=0:d=0.2"
    if ass_name:
        # The worker owns the basename and sets cwd, so drive letters and user filenames stay outside the graph.
        filters += f",ass={ass_name}"
    return filters + "[v]"


def render_command(settings: Settings, source: Path, target: Path, media: Media,
                   clip: Candidate, request: JobRequest, ass_name: str | None) -> list[str]:
    preset = "ultrafast" if request.quality == "low" else settings.ffmpeg_preset
    crf = max(settings.crf, 25) if request.quality == "low" else settings.crf
    command = [settings.executable("ffmpeg"), "-v", "error", "-xerror", "-nostdin", "-n",
               "-protocol_whitelist", "file", "-f", input_format(source),
               "-ss", f"{clip.start_seconds:.6f}", "-i", str(source)]
    if media.audio_streams:
        audio_stream = f"0:{media.audio_streams[0]}"
    else:
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_stream = "1:a:0"
    command += ["-filter_complex_threads", str(settings.cpu_threads),
               "-filter_complex", graph(request, media, settings.fps, ass_name),
               "-map", "[v]", "-map", audio_stream,
               "-t", f"{clip.end_seconds - clip.start_seconds:.6f}", "-map_metadata", "-1",
               "-map_chapters", "-1", "-c:v", "libx264", "-threads:v", str(settings.cpu_threads),
               "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
    if request.normalize_audio:
        command += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    return [*command, str(target)]


def render(settings: Settings, source: Path, target: Path, media: Media,
           clip: Candidate, request: JobRequest, ass_name: str | None,
           cancel: Callable[[], None]) -> None:
    run(render_command(settings, source, target, media, clip, request, ass_name),
        timeout=settings.ffmpeg_timeout, cwd=target.parent, check_cancel=cancel)
