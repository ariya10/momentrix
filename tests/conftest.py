from pathlib import Path

import pytest

from app.config import Settings
from app.schemas import Candidate, Segment, Transcript, Word


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    result = Settings(root=tmp_path, api_token="", minimum_free_bytes=0)
    result.prepare()
    return result


@pytest.fixture
def transcript() -> Transcript:
    first = "The paper bridge held."
    second = "Three mugs sat upright."
    return Transcript(source_filename="sample.mp4", source_duration=120, language="en", segments=[
        Segment(start=0, end=30, text=first, words=[
            Word(start=1 + index, end=1.8 + index, text=word)
            for index, word in enumerate(first.split())
        ]),
        Segment(start=60, end=90, text=second, words=[
            Word(start=61 + index, end=61.8 + index, text=word)
            for index, word in enumerate(second.split())
        ]),
    ])


@pytest.fixture
def clip_candidate() -> Candidate:
    return Candidate(
        start_seconds=0, end_seconds=30, category="Experiment", score=99,
        hook="The paper bridge held", title="The paper bridge test", caption="Testing a folded paper bridge",
        description="A bridge made from paper holds a mug.", hashtags=["#PaperBridge"],
        score_breakdown={"hook": 20, "entertainment": 20, "standalone": 18, "payoff": 13, "relevance": 11},
        selection_reason="The opening experiment has a clear result.",
        supporting_transcript="The paper bridge held.",
        review_flags=[],
    )
