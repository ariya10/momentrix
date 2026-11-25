import json
import os
import re
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from app.config import VIDEO_TYPES


def video_name(name: str) -> str:
    if (
        not name or name != name.strip() or name.endswith(".")
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", name.split(".")[0].rstrip())
        or Path(name).suffix.lower() not in VIDEO_TYPES
    ):
        raise ValueError("Use a plain MP4, MOV, MKV or WEBM filename from input/")
    return name


def child(folder: Path, name: str) -> Path:
    path = folder / name
    if path.parent != folder or path.resolve() != folder.resolve() / name or path.is_symlink():
        raise ValueError("File path is outside the allowed folder or is a symbolic link")
    return path


def source_path(folder: Path, name: str, limit: int) -> Path:
    path = child(folder, video_name(name))
    if not path.is_file():
        raise ValueError("Source video was not found in input/")
    size = path.stat().st_size
    if not 0 < size <= limit:
        raise ValueError("Source video is empty or exceeds the configured size limit")
    return path


def atomic_text(path: Path, data: str) -> None:
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(data, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, data) -> None:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
