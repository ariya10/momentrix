# MOMENTRIX V2 migration and acceptance plan

V2 runs locally on Windows with SQLite and one media worker. React calls FastAPI. FastAPI records the run before sending its ID to an authenticated n8n webhook. Only the backend reads media or invokes local models. The browser can disconnect at any time.

## Baseline, 24 November 2026

The Python 3.11 V1 suite passed all 37 tests in 35.42 seconds, including actual FFmpeg and Ollama integrations. SQLite integrity_check returned ok. The existing database held eight jobs, one historically failed, and none active. Node 24.15.0, npm 11.13.0 and installed Edge and Chrome were detected. The V1 API, legacy dashboard, n8n and Ollama ports all accepted connections. Prior verified end-to-end evidence is in PROGRESS.md.

V1 stores jobs as JSON in SQLite, clip indexes beside media, and campaigns as JSON presets. It lacks durable project/asset identity, revision-specific review and export, time-series signals, a browser editor, and secure n8n callbacks. Its percentage estimates cannot stand in for measured V2 progress. Keep the working services and files in place. Use additive migrations and compatibility reads for historical results.

| Phase | Acceptance check |
| --- | --- |
| 0 · Baseline | Inspect existing source, run tests, verify existing SQLite, create and check an online backup before applying any migration. |
| 1 · Website and API | Compile React, serve the build locally, test browser sessions, migrations and API compatibility. |
| 2 · Projects and assets | Persist projects, fingerprint and validate uploads, produce preview media and retrieve previous work after a restart. |
| 3 · Generation | Persist a run before dispatch, authenticate and deduplicate callbacks, reconnect to real status, exercise n8n. |
| 4 · Evidence | Measure audio and scene/motion signals, keep source timestamps and missing-signal behavior, rank supported intervals. |
| 5 · Framing | Track sampled detections and check stable and lost-target behavior on media. Verify vertical layouts before export. |
| 6 · Editing | Record source-time edits, apply an EDL, remap captions, render and decode preview and export. |
| 7 · Browser tools | Exercise project creation, clip discovery, draft edits, review and download through the website. |
| 8 · Automation and review | Import and exercise workflows; review the current revision, then export only approved clips. |
| 9 · Operations | Measure actual processing, check authentication, queue recovery, storage, CPU load and failure reporting. |
| 10 · Release | Run backend, frontend, browser and real local integration tests. Document observed coverage and pending items in PROGRESS.md. |

Approval is required before activating workflows or credentials in the existing n8n installation. Historical V1 previews remain accessible through the original token-authenticated client. Website sessions access versioned endpoints only.
