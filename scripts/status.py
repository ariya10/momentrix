import argparse
import json
from types import SimpleNamespace

import httpx

from app.api.routes import system_status
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    options = parser.parse_args()
    app = create_app()
    app.state.settings.prepare()
    status = system_status(SimpleNamespace(app=app))
    print(json.dumps(status.model_dump(), indent=2))
    headers = {"X-API-Token": app.state.settings.api_token}
    try:
        with httpx.Client(timeout=4, trust_env=False) as client:
            response = client.get(f"{options.backend.rstrip('/')}/health", headers=headers)
            print(f"Backend HTTP status: {response.status_code}")
    except httpx.HTTPError:
        print("Backend health endpoint unavailable")


if __name__ == "__main__":
    main()
