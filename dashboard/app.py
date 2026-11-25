"""Local clip submission and review through the MOMENTRIX API."""

import os
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
import streamlit as st

# Streamlit puts this script's directory first, where app.py shadows the backend package.
project_root = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, project_root)
try:
    from app.config import Settings
    from app.schemas import TERMINAL, Status
finally:
    sys.path.remove(project_root)

DASHBOARD_URL = os.getenv("MOMENTRIX_DASHBOARD_API_URL", "http://127.0.0.1:8000")
SETTINGS = Settings()
LAYOUTS = {"fit": "Fit with padding", "crop": "Center crop",
           "roi": "Manual region", "split": "Facecam above gameplay",
           "auto_split": "Automatic facecam"}
READY = {Status.COMPLETED, Status.WARNINGS}


class ApiError(RuntimeError):
    pass


def api(method: str, path: str, *, binary: bool = False, **kwargs):
    if urlsplit(DASHBOARD_URL).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ApiError("Use a loopback backend URL for the dashboard.")
    headers = kwargs.pop("headers", {})
    if SETTINGS.api_token:
        headers["X-API-Token"] = SETTINGS.api_token
    try:
        with httpx.Client(base_url=DASHBOARD_URL, timeout=60, trust_env=False) as client:
            response = client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError("The backend could not be reached. Check that it is running.") from exc
    if not response.is_success:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, list):
            detail = "; ".join(item.get("msg", "Invalid input") for item in detail)
        raise ApiError(detail or f"Backend error ({response.status_code})")
    return response.content if binary else response.json()


@st.cache_data(max_entries=2, ttl=300, show_spinner=False)
def preview(path: str) -> bytes:
    return api("GET", path, binary=True)


def region(label: str, key: str) -> dict:
    st.caption(label)
    cols = st.columns(4)
    return {
        field: cols[index].number_input(text, min_value=minimum, value=default, step=1,
                                        key=f"{key}_{field}")
        for index, (field, text, minimum, default) in enumerate((
            ("x", "Left", 0, 0), ("y", "Top", 0, 0),
            ("width", "Width", 2, 320), ("height", "Height", 2, 180),
        ))
    }


def submit_job() -> None:
    st.subheader("New clipping job")
    sources = api("GET", "/sources")
    campaigns = {item["id"]: item for item in api("GET", "/campaigns")}
    with st.container(border=True):
        source = st.selectbox("Local source", sources, index=None, placeholder="Choose a video from input/")
        uploaded = st.file_uploader(
            "Or upload a video",
            type=["mp4", "mov", "mkv", "webm"],
            help="For large videos, copy the file into input/ and choose Local source to save memory.",
        )
        if not campaigns:
            st.error("The backend has no readable campaign presets.")
            return
        campaign_id = st.selectbox("Campaign", list(campaigns), format_func=lambda item: campaigns[item]["name"])
        campaign = campaigns[campaign_id]
        for field, label in (("hook_requires", "The hook must mention"),
                             ("caption_requires", "The caption must mention"),
                             ("required_hashtags", "Required hashtags include"),
                             ("required_keywords", "The clip must contain these spoken terms")):
            if campaign[field]:
                st.caption(f"{label} {', '.join(campaign[field])}.")
        left, right = st.columns(2)
        count = left.number_input("Clip count", min_value=1, max_value=20, value=campaign["count"],
                                  key=f"count_{campaign_id}")
        layout = right.selectbox("Layout", list(LAYOUTS), index=list(LAYOUTS).index(campaign["layout"]),
                                  format_func=LAYOUTS.get, key=f"layout_{campaign_id}")
        minimum, maximum = map(float, (campaign["min_duration"], campaign["max_duration"]))
        if minimum < maximum:
            minimum, maximum = st.slider("Clip duration in seconds", min_value=minimum, max_value=maximum,
                                         value=(minimum, maximum), step=0.5, key=f"duration_{campaign_id}")
        coordinates = {}
        if layout == "roi":
            coordinates["roi"] = region("Source region in pixels", "roi")
        if layout == "split":
            coordinates["facecam"] = region("Facecam region in pixels", "facecam")
            coordinates["gameplay"] = region("Gameplay region in pixels", "gameplay")
        if layout == "auto_split":
            st.caption("Looks for a stable corner facecam in each clip. Uses Fit when detection is inconclusive.")
        with st.expander("Subtitle and export settings"):
            subtitles = st.toggle("Burn in subtitles and export SRT", value=True)
            style, font = st.columns(2)
            position = style.selectbox("Subtitle position", ["bottom", "middle", "top"])
            subtitle_font = font.text_input("Subtitle font", value="Arial")
            opening_hook = st.toggle("Show opening hook on the video")
            normalize_audio = st.toggle("Normalize audio")
            fade_in = st.toggle("Fade in the picture")
            quality = st.selectbox("Export profile", ["standard", "low"], format_func=str.title)
        authorized = st.checkbox("I have permission to use this source video.")
        if not st.button("Start processing", type="primary", disabled=not (authorized and (source or uploaded))):
            return
        if uploaded is not None:
            with st.spinner("Uploading source"):
                uploaded.seek(0)
                result = api(
                    "POST",
                    "/sources",
                    headers={
                        "X-Filename": quote(uploaded.name, safe=""),
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(uploaded.size),
                    },
                    content=iter(lambda: uploaded.read(1024 * 1024), b""),
                )
                source = result["filename"]
        job = api("POST", "/jobs", json={
            "filename": source, "campaign": campaign_id, "count": count, "layout": layout,
            "min_duration": minimum, "max_duration": maximum, "subtitles": subtitles,
            "subtitle_font": subtitle_font, "subtitle_position": position, "opening_hook": opening_hook,
            "normalize_audio": normalize_audio, "fade_in": fade_in,
            "quality": quality, "authorized": authorized, **coordinates,
        })
        st.session_state["active_job"] = job["job_id"]
        st.rerun()


def job_progress(job: dict) -> None:
    stage = job["status"].replace("_", " ").capitalize()
    st.progress(job["progress"], text=f"{stage} · {job['progress']}%")
    if job["error"]:
        st.error(job["error"])
    for warning in job["warnings"]:
        st.warning(warning)


@st.fragment(run_every=3)
def watch_job(job_id: str) -> None:
    try:
        job = api("GET", f"/jobs/{job_id}")
        if job["status"] in TERMINAL:
            st.rerun()
        job_progress(job)
        if job["cancel_requested"]:
            st.caption("Cancellation requested")
        elif st.button("Cancel processing"):
            api("POST", f"/jobs/{job_id}/cancel")
            st.rerun()
    except ApiError as exc:
        st.error(str(exc))


def review_clips(job: dict) -> None:
    job_path = f"/jobs/{job['job_id']}"
    clips = api("GET", f"{job_path}/clips")
    st.download_button("Download metadata CSV", api("GET", f"{job_path}/metadata.csv", binary=True),
                       "metadata.csv", "text/csv")
    if not clips:
        st.info("This job produced no clips for review.")
        return
    clip_map = {clip["clip_id"]: clip for clip in clips}
    identifier = st.selectbox("Clip", list(clip_map),
                             format_func=lambda value: f"{clip_map[value]['title']} · {clip_map[value]['score']}/100",
                             key=f"choice_{job['job_id']}")
    clip = clip_map[identifier]
    clip_key = f"{job['job_id']}_{identifier}"
    path = f"{job_path}/clips/{identifier}"
    video = preview(f"{path}/download")
    left, right = st.columns([1, 1.6])
    with left:
        st.video(video, format="video/mp4")
        st.download_button("Download MP4", video, clip["file"], "video/mp4")
        if clip["subtitle_file"]:
            st.download_button("Download SRT", api("GET", f"{path}/subtitle", binary=True),
                               clip["subtitle_file"], "application/x-subrip")
    with right:
        st.caption(f"{clip['start_seconds']:.2f}s–{clip['end_seconds']:.2f}s in source  ·  "
                   f"{clip['score']}/100 ranking score")
        detection = clip.get("facecam_detection")
        if detection and detection["region"]:
            st.caption(f"Facecam detected in {detection['matching_frames']} of "
                       f"{detection['sampled_frames']} sampled frames. Check the crop in the preview.")
        st.text(clip["selection_reason"])
        with st.form(f"metadata_{clip_key}"):
            hook = st.text_input("Opening hook", clip["hook"], disabled=clip["hook_burned"])
            title = st.text_input("Shorts title", clip["title"])
            caption = st.text_area("Reels caption", clip["caption"])
            description = st.text_area("Description", clip["description"])
            tags = st.text_input("Hashtags", " ".join(clip["hashtags"]))
            if st.form_submit_button("Save metadata"):
                api("PUT", f"{path}/metadata", json={
                    "hook": hook, "title": title, "caption": caption,
                    "description": description, "hashtags": tags.split(),
                })
                st.rerun()
        with st.expander("Review checklist", expanded=True):
            for item in dict.fromkeys([*clip["manual_review"], *clip["review_flags"]]):
                st.text(f"• {item}")
        with st.form(f"review_{clip_key}"):
            choices = ["pending", "approved", "rejected"]
            choice = st.selectbox("Review status", choices, index=choices.index(clip["review"]["status"]),
                                  format_func=str.title)
            note = st.text_area("Review note", clip["review"]["note"])
            if st.form_submit_button("Save review", type="primary"):
                api("PUT", f"{path}/review", json={"status": choice, "note": note})
                st.rerun()


st.set_page_config(page_title="MOMENTRIX", layout="wide")
st.title("MOMENTRIX")
try:
    jobs = api("GET", "/jobs")
    history = {job["job_id"]: job for job in jobs}
    options = [None, *history]
    active = st.session_state.pop("active_job", None)
    if active in history:
        st.session_state["history_selection"] = active
    selected = st.sidebar.selectbox(
        "Job history", options,
        format_func=lambda value: "New job" if value is None else
        f"{history[value]['request']['filename']} · {value[:8]}",
        key="history_selection",
    )
    if selected is None:
        submit_job()
    else:
        job = api("GET", f"/jobs/{selected}")
        st.subheader(job["request"]["filename"])
        if job["status"] in TERMINAL:
            job_progress(job)
            if job["status"] in READY:
                review_clips(job)
        else:
            watch_job(selected)
except ApiError as exc:
    st.error(str(exc))
