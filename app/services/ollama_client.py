import json
from collections.abc import Callable
from typing import TypeVar

import httpx
from pydantic import ValidationError, model_validator

from app.config import Settings
from app.schemas import Candidate, Proposal

Result = TypeVar("Result")


class ModelProposal(Proposal):
    @model_validator(mode="before")
    @classmethod
    def normalize_hashtags(cls, value):
        if not isinstance(value, dict) or not isinstance(value.get("clips"), list):
            return value
        for clip in value["clips"]:
            if isinstance(clip, dict) and isinstance(clip.get("hashtags"), list):
                clip["hashtags"] = [
                    "#" + tag.strip().lstrip("#") if isinstance(tag, str) else tag
                    for tag in clip["hashtags"]
                ]
        return value


def parse_response(payload: dict, ranges: list[list[float]]) -> list[Candidate]:
    if payload.get("done_reason") == "length":
        raise ValueError("Ollama reached its output limit")
    proposal = ModelProposal.model_validate_json(payload["message"]["content"])
    result = []
    for clip in proposal.clips:
        if clip.range_id >= len(ranges):
            raise ValueError("Ollama selected an unknown interval")
        start, end = ranges[clip.range_id]
        result.append(Candidate(**clip.model_dump(exclude={"range_id"}),
                                start_seconds=start, end_seconds=end))
    return result


def availability(settings: Settings) -> tuple[bool, bool]:
    try:
        with httpx.Client(timeout=4, trust_env=False) as client:
            response = client.get(f"{settings.ollama_base}/api/tags")
            response.raise_for_status()
            names = {model["name"] for model in response.json()["models"]
                     if not model.get("remote_host") and not model.get("remote_model")}
        configured = settings.ollama_model
        if ":" not in configured.rsplit("/", 1)[-1]:
            configured += ":latest"
        return True, configured in names
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return False, False


def ask(settings: Settings, system: str, data: dict, cancel: Callable[[], None],
        *, ranges: list[list[float]], keep_alive: str | int = 0) -> list[Candidate]:
    schema = Proposal.model_json_schema()
    candidate = schema["$defs"]["ProposedHighlight"]
    fields = candidate["properties"]
    primary = ("range_id", "supporting_transcript")
    if ranges:
        fields["range_id"]["enum"] = list(range(len(ranges)))
    candidate["properties"] = {key: fields[key] for key in (*primary, *(key for key in fields if key not in primary))}
    candidate["required"] = list(candidate["properties"])
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({
                **data, "allowed_ranges": [[index, *times] for index, times in enumerate(ranges)],
            }, ensure_ascii=False)},
        ],
        "stream": False,
        "think": False,
        "format": schema,
        "keep_alive": keep_alive,
        "options": {"temperature": 0.15, "num_ctx": 8192, "num_predict": 2400,
                    "num_thread": settings.cpu_threads},
    }
    return structured_request(settings, payload, lambda reply: parse_response(reply, ranges),
                              cancel, purpose="selection")


def structured_request(settings: Settings, payload: dict, parse: Callable[[dict], Result],
                       cancel: Callable[[], None], *, purpose: str) -> Result:
    failure = "unknown error"
    with httpx.Client(timeout=httpx.Timeout(settings.ollama_timeout, connect=5), trust_env=False) as client:
        for _ in range(settings.ollama_attempts):
            cancel()
            try:
                response = client.post(f"{settings.ollama_base}/api/chat", json=payload)
                if response.status_code == 404:
                    raise RuntimeError(f"Ollama model {settings.ollama_model} is missing. Pull it with Ollama.")
                response.raise_for_status()
                result = parse(response.json())
                cancel()
                return result
            except ValidationError as exc:
                codes = sorted({error["type"] for error in exc.errors(include_input=False)})
                failure = ", ".join(codes)
            except (httpx.HTTPError, TypeError, KeyError, AttributeError, ValueError) as exc:
                failure = type(exc).__name__
    cancel()
    raise RuntimeError(f"Ollama returned no valid {purpose} after {settings.ollama_attempts} attempts ({failure}).")
