from pathlib import Path

from pydantic import ValidationError

from app.config import ROOT
from app.schemas import Campaign, JobRequest
from app.utils.files import child


def directory(root: Path) -> Path:
    local = root / "campaigns"
    return local if local.is_dir() else ROOT / "campaigns"


def load_campaign(root: Path, name: str) -> Campaign:
    try:
        return Campaign.model_validate_json(child(directory(root), f"{name}.json").read_bytes())
    except FileNotFoundError as exc:
        raise ValueError("Unknown campaign preset") from exc
    except ValidationError as exc:
        raise ValueError("Campaign preset has invalid fields or values") from exc


def resolve_request(request: JobRequest, campaign: Campaign) -> JobRequest:
    if campaign.authorization_required and not request.authorized:
        raise ValueError("Confirm that you have permission to use the source video")
    minimum = request.min_duration if request.min_duration is not None else campaign.min_duration
    maximum = request.max_duration if request.max_duration is not None else campaign.max_duration
    if not campaign.min_duration <= minimum <= maximum <= campaign.max_duration:
        raise ValueError("Clip duration bounds must be ordered and fall within the campaign range")
    return request.model_copy(update={"min_duration": minimum, "max_duration": maximum,
                                      "count": request.count or campaign.count,
                                      "layout": request.layout or campaign.layout})
