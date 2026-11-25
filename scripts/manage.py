import argparse
from pathlib import Path
from secrets import token_urlsafe

from app.config import ROOT, Settings
from app.utils.files import atomic_text, child, video_name
from app.utils.process import run


def configure_token() -> None:
    path = ROOT / ".env"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = current.splitlines()
    if Settings().api_token:
        print("A local API token is already configured.")
        return
    lines = [line for line in lines if line.partition("=")[0].strip() != "MOMENTRIX_API_TOKEN"]
    lines.append(f"MOMENTRIX_API_TOKEN={token_urlsafe(32)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Generated a local API token in .env.")


def configure_n8n(settings: Settings) -> None:
    values = {
        "MOMENTRIX_WEBHOOK_SECRET": settings.webhook_secret or token_urlsafe(32),
        "MOMENTRIX_SERVICE_TOKEN": settings.service_token or token_urlsafe(32),
    }
    if len({settings.api_token, *values.values()}) != 3:
        raise ValueError("The existing MOMENTRIX tokens must be distinct.")
    if settings.webhook_secret and settings.service_token:
        print("Both n8n runtime credentials are already configured.")
        return
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition("=")[0].strip() not in values]
    lines.extend(f"{key}={value}" for key, value in values.items())
    atomic_text(path, "\n".join(lines) + "\n")
    print("Saved the distinct local n8n runtime credentials in .env.")


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("verify")
    subcommands.add_parser("whisper")
    subcommands.add_parser("token")
    subcommands.add_parser("n8n-credentials")
    sample = subcommands.add_parser("sample")
    sample.add_argument("--filename", required=True)
    sample.add_argument("--wav", type=Path, required=True)
    options = parser.parse_args()
    settings = Settings()
    settings.prepare()
    if options.command == "verify":
        import cv2
        import fastapi
        import faster_whisper
        import httpx
        import pydantic
        import uvicorn

        print("Runtime imports verified.")
    elif options.command == "whisper":
        from app.services.transcription import model_location

        model_location(settings, local_only=False)
        print("Whisper model is available in the project cache.")
    elif options.command == "token":
        configure_token()
    elif options.command == "n8n-credentials":
        configure_n8n(settings)
    else:
        target = child(settings.root / "input", video_name(options.filename))
        if target.exists():
            parser.error("A source with that name already exists.")
        run([settings.executable("ffmpeg"), "-v", "error", "-nostdin", "-n", "-f", "lavfi",
             "-i", "testsrc2=size=640x360:rate=30", "-i", str(options.wav.resolve()), "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(target)],
            cwd=settings.root / "cache", timeout=180)
        print("Created an authorized synthetic sample in input/.")


if __name__ == "__main__":
    main()
