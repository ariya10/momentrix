# MOMENTRIX Handover

## Workspace

Primary project: `D:\Downloads\momentrix-starter\momentrix`

Read `AGENTS.md`, `PROGRESS.md`, `VERSION_2_PLAN.md`, and this audit before changes.

## Verified baseline

- 50 Python unit tests pass.
- 16 Python integration tests pass.
- React production build passes.
- React Vitest suite passes 3 tests.
- The n8n connection-test workflow JSON parses successfully; live Docker import remains unverified.
- FastAPI and n8n are running locally. The Docker bridge to authenticated FastAPI health succeeded.
- The selected `.env` API token was rotated; do not reuse or disclose the prior value.
- Playwright created an authorized-sample project and run successfully. The run is awaiting n8n activation, not execution.
- On 24 November 2026, FastAPI, Vite, and n8n were stopped for next-day continuation.

## Recovery continuation · 25 November 2026

- Docker 29.9.3 and the existing `n8n` container are running.
- Ollama has `qwen2.5:3b`; FastAPI and React Studio are running.
- The production n8n connection webhook returned `ok`.
- The n8n container reached authenticated FastAPI health through `host.docker.internal:8000`.
- MCP discovery confirmed the active hardened main pipeline, hardened error handler, and review/export workflows.
- 56 Python unit tests passed, 20 integration tests passed, 5 Vitest tests passed, the React build passed, and `pip check` passed.
- Real authorized creator footage and campaign compliance remain external human-verification blockers.

## Live runtime · 25 November 2026

- Production Studio is available at `http://127.0.0.1:8000/studio/`.
- FastAPI, n8n, Docker, and Ollama are running.
- The live Playwright desktop/mobile navigation test passed, including authenticated n8n connection verification.
- The production run was left running. Use `.\.venv\Scripts\python.exe -m scripts.manage` for local administrative operations and `.\scripts\show_studio_key.ps1` to display the Studio key locally.

## Current milestone · 25 November 2026

Docker Desktop, the original n8n container, FastAPI and Vite are running. Three existing MOMENTRIX workflows were repaired and published through the public API. The previously absent export workflow was published once. The production connection test passed with the local Header Auth credential.

Live Playwright runs verified Fast in n8n execution `15` and the Quality preset with a tracked face and karaoke revision in execution `17`. Both passed through the approval gate to authenticated HTTP 206 downloads. All 73 Python tests, three Vitest tests, and the production build passed. See [PROGRESS.md](PROGRESS.md) for timings and media checks. Workflow IDs, credential types and repair instructions are in [N8N_INTEGRATION.md](N8N_INTEGRATION.md).

For the current build, start with the [Windows run guide](RUN_GUIDE.md). The 12-minute production run used n8n execution `20`. A focused browser test then regenerated publishing metadata for that clip and verified the reviewed export. An isolated test accepted exactly 2 GiB. Optional scheduler callbacks were exercised in a disposable n8n profile.

## Safe commands

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not integration"
.\.venv\Scripts\python.exe -m pytest -m integration
cd frontend
npm run build
npm test
```

## Resume rules

- Preserve V1 media and successful exports.
- Create the online SQLite backup before any schema upgrade.
- Keep separate V1 API token, V2 studio key, n8n service credential, and webhook secret.
- Mark real-media and live-n8n behavior as unverified until observed.
- Update `PROGRESS.md` after every meaningful implementation task.
