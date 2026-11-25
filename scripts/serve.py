import argparse
import ipaddress

import uvicorn
from filelock import Timeout

from app.config import Settings
from app.main import create_app, worker_lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    settings = Settings()
    if not ipaddress.ip_address(options.host).is_loopback and not settings.api_token:
        parser.error("Set MOMENTRIX_API_TOKEN before binding a non-loopback address.")
    settings.prepare()
    try:
        with worker_lock(settings):
            pass
    except Timeout:
        print("MOMENTRIX already has a backend running for this workspace. Use the existing backend.")
        return

    uvicorn.run(create_app(settings), host=options.host, port=options.port,
                access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
