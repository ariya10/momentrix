import csv
import io
from pathlib import Path

from app.schemas import Clip
from app.utils.files import atomic_text, write_json


def spreadsheet_text(value: str) -> str:
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export_metadata(folder: Path, clips: list[Clip]) -> None:
    table = io.StringIO(newline="")
    writer = csv.writer(table)
    writer.writerow(["clip_id", "start_seconds", "end_seconds", "score", "hook", "title",
                     "caption", "description", "hashtags", "selection_reason", "review", "review_note"])
    for clip in clips:
        write_json(folder / f"{clip.clip_id}_metadata.json", clip)
        atomic_text(folder / f"{clip.clip_id}_metadata.txt", "\n".join([
            clip.title, "", f"Hook: {clip.hook}", "", clip.caption, " ".join(clip.hashtags), "",
            clip.description, "", f"Source seconds: {clip.start_seconds:.3f}–{clip.end_seconds:.3f}",
            f"Ranking score: {clip.score}/100", clip.selection_reason, "",
        ]))
        writer.writerow([
            clip.clip_id, clip.start_seconds, clip.end_seconds, clip.score,
            *(spreadsheet_text(value) for value in (
                clip.hook, clip.title, clip.caption, clip.description, " ".join(clip.hashtags),
                clip.selection_reason, clip.review.status, clip.review.note,
            )),
        ])
    atomic_text(folder / "metadata.csv", "\ufeff" + table.getvalue())
    write_json(folder / "clips.json", [clip.model_dump(mode="json") for clip in clips])
