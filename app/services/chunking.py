import json
from collections.abc import Iterator
from dataclasses import dataclass

from app.schemas import Segment


@dataclass(frozen=True)
class Chunk:
    start: float
    end: float
    rows: tuple[str, ...]


def encode_row(segment: Segment, limit: int) -> str:
    row = [round(segment.start, 3), round(segment.end, 3), segment.text]
    encoded = json.dumps(row, ensure_ascii=False)
    while len(encoded.encode("utf-8")) > limit:
        row[2] = row[2][:len(row[2]) // 2]
        encoded = json.dumps(row, ensure_ascii=False)
    return encoded


def chunks(segments: list[Segment], budget: int = 8_200) -> Iterator[Chunk]:
    if budget < 128:
        raise ValueError("Transcript character budget must be at least 128")
    items = sorted((s for s in segments if s.text.strip() and s.end > s.start),
                   key=lambda s: s.start)
    rows = [encode_row(segment, budget - 1) for segment in items]
    left = 0
    while left < len(items):
        right, remaining = left, budget
        start = items[left].start
        end = start
        while right < len(items) and items[right].start < start + 300:
            row = rows[right]
            row_size = len(row.encode("utf-8")) + 1
            if right > left and row_size > remaining:
                break
            remaining -= row_size
            end = max(end, items[right].end)
            right += 1
        yield Chunk(start, end, tuple(rows[left:right]))
        if right == len(items):
            return
        next_left = left + 1
        while next_left < right and items[next_left].start < end - 60:
            next_left += 1
        left = next_left
