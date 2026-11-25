# MOMENTRIX Architecture

## Runtime

React is served by FastAPI at `/studio/`. FastAPI remains the application-state authority and media-service boundary. A single persistent worker executes heavy media jobs. SQLite stores V1 jobs and V2 projects, assets, runs, clips, campaigns, sessions, and tasks.

## V1 compatibility

V1 jobs use the `/jobs` API and existing JSON payloads in SQLite. Legacy jobs are synchronized into V2 compatibility rows. V1 media remains under `output/` and V1 dashboard behavior is preserved.

## V2

Browser sessions use a separate studio credential and cookie-compatible session. n8n uses a separate webhook secret and internal service credential. n8n does not receive media files or Ollama/FFmpeg access. It dispatches and monitors validated run IDs.

## Processing

The worker probes media, transcribes, analyzes evidence, ranks candidates, chooses layouts, renders previews/exports, and writes quality reports. SQLite migrations create an online backup before schema upgrades. Heavy operations stay in the existing worker process.

## Storage

- `input/` authorized source uploads.
- `storage/` project and asset working files.
- `output/` generated media and reports.
- `cache/` models and derived products.
- `data/backups/` SQLite migration and audit backups.
- `logs/` rotating application logs.

