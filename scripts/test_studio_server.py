"""Start an isolated local API for browser tests. The test workspace is newly created."""
import argparse
from pathlib import Path
import shutil
from tempfile import mkdtemp
import secrets

import uvicorn
from app.config import Settings
from app.main import create_app
from app.services.transcription import model_location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8129)
    args = parser.parse_args()
    installed = Settings()
    root = Path(mkdtemp(prefix="browser-v2-",dir=installed.root/"cache"))
    settings = Settings(root=root,ffmpeg=installed.executable("ffmpeg"),ffprobe=installed.executable("ffprobe"),
                        whisper_model=model_location(installed),api_token=secrets.token_urlsafe(32),
                        webhook_secret=secrets.token_urlsafe(32),service_token=secrets.token_urlsafe(32),
                        n8n_url="http://127.0.0.1:1",cpu_threads=2)
    settings.prepare()
    sample = installed.root/"input"/"Momentrix sample.mp4"
    if sample.is_file():
        shutil.copyfile(sample,root/"input"/sample.name)
    # These two keys belong to this disposable test workspace only.
    (root/"data"/"callback-test.key").write_text(settings.service_token, encoding="ascii")
    print(f"Isolated studio root {root}",flush=True)
    uvicorn.run(create_app(settings),host="127.0.0.1",port=args.port,access_log=False,proxy_headers=False)


if __name__=="__main__":
    main()

