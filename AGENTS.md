# MOMENTRIX workspace instructions

- Read `PROGRESS.md` and inspect the workspace when resuming. Update progress with observed results after each phase.
- Use Python 3.11 and a workspace-local `.venv`. Invoke its Python executable directly on Windows.
- Keep the application local and single-worker by default. Use Faster-Whisper and Ollama locally, and keep timestamp, file, and campaign validation in Python.
- Preserve source files and existing successful exports. Use argument lists for FFmpeg and FFprobe, and constrain file access to project storage.
- Require user confirmation of source authorization and keep review separate from publishing or campaign submission.
- Ask before large downloads, system-wide installs, or privileged actions. Preserve the existing Docker and n8n setup and data.
- Use pytest for unit tests and record which external integrations and real media runs were actually verified.
- Follow VERSION_2_PLAN.md for V2. Use the React website for all V2 operations. Preserve the V1 API and generated media.
- Back up SQLite with its online backup API before every schema upgrade. Keep browser sessions, internal callbacks and n8n webhook credentials separate. Keep heavy operations on the existing worker.
- A preview may be reviewed. Export requires explicit approval of the current revision. Record actual Vitest, Playwright and end-to-end results and mark unverified requirements pending.
