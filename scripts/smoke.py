import argparse
import time

import httpx

from app.config import Settings
from app.schemas import TERMINAL, Job, Status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--hook", action="store_true")
    options = parser.parse_args()
    headers = {"X-API-Token": Settings().api_token}
    with httpx.Client(base_url=options.backend, headers=headers, trust_env=False, timeout=20) as api:
        response = api.post("/jobs", json={"filename": options.filename, "count": options.count,
                                           "authorized": True, "opening_hook": options.hook})
        if not response.is_success:
            raise SystemExit(f"Job submission failed ({response.status_code}): {response.text}")
        job = Job.model_validate_json(response.content)
        path = f"/jobs/{job.job_id}"
        start = time.monotonic()
        print(f"Job {job.job_id}", flush=True)
        last = None
        while True:
            response = api.get(path)
            response.raise_for_status()
            job = Job.model_validate_json(response.content)
            progress = (job.status, job.progress)
            if progress != last:
                print(f"{job.status} {job.progress}%", flush=True)
                last = progress
            if job.status in TERMINAL:
                break
            if time.monotonic() - start > options.timeout:
                raise SystemExit(f"Monitoring timed out. Job {job.job_id} remains on the backend.")
            time.sleep(2)
        for warning in job.warnings:
            print(warning)
        response = api.get(f"{path}/clips")
        response.raise_for_status()
        clips = response.json()
        if job.status not in {Status.COMPLETED, Status.WARNINGS} or not clips:
            raise SystemExit(job.error or "Smoke test had no verified clip exports.")
        clip = clips[0]
        with api.stream("GET", f"{path}/clips/{clip['clip_id']}/download") as video:
            video.raise_for_status()
            if not next(video.iter_bytes(), b""):
                raise SystemExit("Clip download was empty.")
        print(f"Verified {len(clips)} downloadable clip(s) in {time.monotonic() - start:.1f}s.")


if __name__ == "__main__":
    main()
