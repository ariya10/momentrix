from collections.abc import Callable
from math import ceil, floor, hypot
from pathlib import Path
from statistics import median

from app.config import Settings
from app.schemas import Candidate, FacecamDetection, Region
from app.services.audio import Media, input_format
from app.utils.process import run

SAMPLE_COUNT = 7
STABILITY_RADIUS = 0.085


def infer_region(frames: list[list[Region]], width: int, height: int) -> FacecamDetection:
    """Infer a static crop from a small face repeatedly seen in one corner."""
    def in_corner(face: Region) -> bool:
        x = (face.x + face.width / 2) / width
        y = (face.y + face.height / 2) / height
        return ((x <= 0.30 or x >= 0.70) and (y <= 0.36 or y >= 0.64)
                and face.width <= width * 0.26 and face.height <= height * 0.35)

    def distance(left: Region, right: Region) -> float:
        dx = left.x + left.width / 2 - right.x - right.width / 2
        dy = left.y + left.height / 2 - right.y - right.height / 2
        return hypot(dx / width, dy / height)

    corners = [[face for face in faces if in_corner(face)] for faces in frames]
    groups = []
    for seed in (face for faces in corners for face in faces):
        matches = []
        for faces in corners:
            nearby = [face for face in faces if distance(seed, face) <= STABILITY_RADIUS
                      and max(seed.width, face.width) <= 2 * min(seed.width, face.width)]
            if nearby:
                matches.append(min(nearby, key=lambda face: distance(seed, face)))
        groups.append((seed, matches))

    seed, matches = max(groups, key=lambda group: len(group[1]), default=(None, []))
    result = FacecamDetection(region=None, sampled_frames=len(frames), matching_frames=len(matches))
    minimum = max(3, ceil(len(frames) * 0.6))
    if seed is None or len(matches) < minimum:
        return result
    if any(len(other) >= minimum and distance(seed, alternate) > STABILITY_RADIUS * 1.5
           for alternate, other in groups):
        return result

    head_width = median(face.width for face in matches)
    head_height = median(face.height for face in matches)
    left = max(0, floor(min(face.x for face in matches) - head_width * 0.75))
    right = min(width, ceil(max(face.x + face.width for face in matches) + head_width * 0.75))
    top = max(0, floor(min(face.y for face in matches) - head_height * 0.55))
    bottom = min(height, ceil(max(face.y + face.height for face in matches) + head_height * 1.05))
    if right - left <= width * 0.50 and bottom - top <= height * 0.60:
        result.region = Region(x=left, y=top, width=right - left, height=bottom - top)
    return result


def detect(settings: Settings, source: Path, media: Media, clip: Candidate, staging: Path,
           cancel: Callable[[], None]) -> FacecamDetection:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("OpenCV is unavailable") from exc

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    duration = clip.end_seconds - clip.start_seconds
    frames = []
    target = staging / "facecam_sample.png"
    try:
        detector = cv2.CascadeClassifier(str(cascade_path))
        if detector.empty():
            raise RuntimeError("The bundled OpenCV face detector could not be loaded")
        for index in range(SAMPLE_COUNT):
            position = clip.start_seconds + duration * (index + 0.5) / SAMPLE_COUNT
            target.unlink(missing_ok=True)
            run([
                settings.executable("ffmpeg"), "-v", "error", "-nostdin", "-n",
                "-protocol_whitelist", "file", "-f", input_format(source), "-threads", str(settings.cpu_threads),
                "-ss", f"{position:.6f}", "-i", str(source), "-map", f"0:{media.video_stream}",
                "-filter_threads", str(settings.cpu_threads), "-vf",
                "scale=768:768:force_original_aspect_ratio=decrease:force_divisible_by=2,format=gray",
                "-frames:v", "1", "-threads:v", "1", "-update", "1", str(target),
            ], cwd=staging, timeout=30, check_cancel=cancel)
            faces = []
            if target.is_file():
                image = cv2.imdecode(np.frombuffer(target.read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                if image is not None:
                    height, width = image.shape
                    detections = detector.detectMultiScale(cv2.equalizeHist(image), scaleFactor=1.1,
                                                           minNeighbors=5, minSize=(18, 18))
                    for x, y, w, h in detections:
                        left, right = round(x * media.width / width), round((x + w) * media.width / width)
                        top, bottom = round(y * media.height / height), round((y + h) * media.height / height)
                        if right - left >= 2 and bottom - top >= 2:
                            faces.append(Region(x=left, y=top, width=right - left, height=bottom - top))
            frames.append(faces)
    except cv2.error as exc:
        raise RuntimeError("OpenCV could not analyze the sampled video frames") from exc
    finally:
        target.unlink(missing_ok=True)
    return infer_region(frames, media.width, media.height)
