# MOMENTRIX progress

## 24 November 2026 · Mandatory V2 audit

- Inspected the existing source, V2 React website, FastAPI routes, worker, migration, tests, n8n exports, and continuity documents.
- Python baseline: 50 unit tests passed; 16 integration tests passed.
- React baseline: production build passed.
- Dependency check: `pip check` passed.
- SQLite baseline: integrity check returned `ok`; 9 jobs existed.
- Created an online SQLite audit backup and verified it: `data/backups/audit-backup-20261124-145057.sqlite3`.
- Identified at the start of the audit that Vitest and Playwright coverage were missing; focused Vitest and database-backed Playwright coverage have now been added.
- Live n8n activation is intentionally pending approval.
- Added `PROJECT_AUDIT.md`, `TASKS.md`, `ARCHITECTURE.md`, `KNOWN_ISSUES.md`, and `HANDOVER.md`.
- Added a focused Vitest suite for FastAPI error handling and time/date formatting.
- Added `automation/workflows/00_connection_test.json`; live import and Docker connectivity remain unverified.
- 24 November 2026 follow-up: React Vitest passed 3 tests and the React production build passed. The n8n connection workflow parsed successfully as JSON.
- 24 November 2026 live continuation: started FastAPI and Vite; authenticated backend health and n8n health returned `ok`.
- Started the existing n8n Docker container and verified `host.docker.internal:8000/health` through the Docker bridge with the API credential.
- Verified Microsoft Edge could open `/studio/`, enter the local studio key, and reach the authenticated dashboard.
- Playwright follow-up: 1 database-backed desktop/mobile navigation test passed. The authorized upload test was skipped because no `MOMENTRIX_E2E_VIDEO` sample was supplied.
- The exposed `.env` API token was rotated. Authenticated FastAPI health and the Docker bridge both passed with the replacement token.
- An n8n `MOMENTRIX V2 - Backend Connection Test` workflow was imported and published. n8n 2.48.8 requires this regular deployment workflow to be activated through the editor toggle; direct CLI activation is unsupported.
- The production webhook was not registered until editor activation, so execution remains pending the UI toggle.

## 24 November 2026 · Stopped for tomorrow

- Stopped FastAPI, Vite, and the n8n Docker container.
- Preserved the rotated `.env` API token, importable workflows, SQLite data, React build, and Playwright evidence.
- No further n8n activation or generation was performed.
- 24 November 2026 completion pass: rotated the exposed `.env` API token and restarted FastAPI.
- Verified authenticated FastAPI health after rotation and repeated the Docker bridge test successfully.
- Restarted n8n and verified `host.docker.internal:8000/health` through Docker.
- Playwright authorized-sample test passed. Project `d275ed4e8f4442ad8c9cc0ba68bf1b0f` and persistent run `838f30b5a7034636b43eed7fc04a9e4a` were created; status remained `awaiting_automation` because production n8n activation was not enabled.

### Current blockers

- No approved live n8n credentials for activation.
- Real authorized source campaigns remain pending human verification.
- Frontend unit coverage, database-backed browser navigation, and authorized upload persistence are verified. Full real-media processing, n8n activation, and campaign-specific review remain pending.

### Exact next development step

Approve n8n production activation, update the Header Auth credential with the rotated local API token, and execute the connection-test workflow. Then run the generation workflow with the persistent authorized sample run.

## Phase 1 · Environment

- Inspected the two-file starter and created a local Python 3.11 virtual environment.
- Ollama responded on port 11434. Qwen 2.5 3B was absent. The user approved downloading Qwen 2.5 3B and Faster-Whisper base.en.
- FFmpeg and FFprobe were absent from PATH. Docker CLI was installed but could not reach its engine. n8n health did not respond.
- The D drive reported roughly 113 GiB available. Windows reported 16 logical processors, 15.6 GiB of physical RAM, and Intel UHD Graphics via a fallback after CIM denied access. Whisper stays on CPU, and Ollama reported 100% CPU for Qwen.
- Installed the workspace Python requirements and verified imports. `pip check` reported no broken requirements. Downloaded and checked portable FFmpeg and FFprobe 9.1 in the workspace. Both requested local models are available.

## Phase 2 · Transcription

- Added media probing, WAV extraction, Faster-Whisper VAD and word timestamps, and a cache keyed on file contents and transcription settings.
- Verified FFprobe and WAV extraction on generated media. The live API produced a timestamped Whisper transcript from a synthesized Windows Speech sample.

## Phase 3 · Highlight selection

- Added bounded transcript windows and structured Ollama responses. Python checks exact spoken evidence, duration and campaign rules, then ranks and deduplicates candidates.
- Verified the schema response against the real local Qwen 2.5 3B model. Unit tests cover malformed responses, ranking, overlap and campaign rules.

## Phase 4 · Rendering

- Added fit, center crop, manual ROI and manually configured facecam/gameplay split layouts, with optional normalization, hook overlay and SRT/ASS captions.
- All four FFmpeg integration renders passed full decode and stream checks. Tests used an input filename with spaces and Unicode.

## Phase 5 · API and worker

- Added a persistent SQLite queue, nonblocking API, cancellation, restart recovery, guarded downloads, and editable clip metadata and review.
- Verified job creation, authorization, polling, cancellation, restart recovery, local access, downloads and review with API tests. A live Uvicorn backend answered health checks.

## Phase 6 · n8n

- Started the existing Docker Desktop and n8n container. Read the installed n8n version as 2.48.8.
- Created the workflow with a 30-second poll, terminal-state branches and deadline. Verified the Docker bridge returned 401 without a token and 200 with the configured token on the loopback-bound backend.
- Imported and executed the workflow in an isolated n8n profile inside the existing container. The first run verified the terminal warning branch. The final run reached Success output with status `completed` for job `84a7fff6344b4853abfc5074c846b6ff`, which reused a cached transcript and exported one verified clip in 70.69 seconds. The importable workflow and credential setup steps are ready for the main n8n profile.

## Phase 7 · Dashboard

- Added a dark Streamlit dashboard for job submission, progress, cancellation, video previews, downloads, editable metadata, and review. The service health endpoint responded. Streamlit AppTest rendered the configuration screen and the verified clip preview, metadata editor, and review form against the live FastAPI backend.
- Fixed a startup import collision caused by Streamlit placing the dashboard script directory first. Reproduced the error in a live Streamlit session, then verified the same session entry point rendered the new job form after the fix. A regression test exercises the same import path order.
- Raised the dashboard upload limit to accommodate a 2 GiB video plus multipart headers and streamed dashboard-to-API transfers in 1 MiB chunks. A live dashboard session accepted a 256 MiB multipart upload, and FastAPI accepted and probed an exact 2 GiB synthetic MP4. The 24 unit tests passed.

## Phase 8 · Verification

- The final suite passed 29 tests, including real FFmpeg renders for all four layouts, silent video handling, and a structured response from local Ollama. Pytest reported a dependency deprecation warning from Starlette’s TestClient.
- The first two real smoke tests revealed that Qwen can omit hashtag prefixes and select the bounds of a single phrase. Python now normalizes hashtag prefixes and supplies eligible intervals by ID.
- The uncached API job `32f7534050584dbf9798e3ce874f55ae` completed with warnings from the 44.03-second authorized synthetic speech source. Qwen selected one eligible highlight from the three requested. FFmpeg exported and fully decoded a 41.30-second 1080 × 1920, 30 FPS H.264/AAC clip.
- The job took 148.62 seconds on the local machine, including 11.64 seconds for transcription, 105.84 seconds for Ollama selection, and 28.56 seconds for rendering. The smoke script verified an authenticated MP4 download. Visual inspection showed the burned hook and captions in one frame, and decoded source and output audio aligned in the sampled speech window. The SRT contains 26 phrases.
- Real creator footage and campaign-specific visual compliance remain for human review.

## Phase 9 · Documentation

- Added Windows setup, architecture, API usage, n8n credential setup and troubleshooting to `README.md`.

## Phase 10 · Automatic facecam

- Reverified the v1 baseline before extending it. Both local services responded and all 30 baseline tests passed.
- Added **Automatic facecam** as an opt-in layout in the dashboard and API. It samples seven frames per selected clip, uses OpenCV to estimate a fixed corner crop, and passes that crop to the existing split-screen renderer. Inconclusive results use Fit and add a job warning. The verified clip metadata records the crop and frame counts.
- Verified the detector against an authorized synthetic video with a [public-domain NASA portrait](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.astronaut) overlaid in one corner. It found the face in all seven samples and returned no crop for the face-free control.
- The live API job `880f65160b0b4a1d842f255dfefd5fd1` completed and exported a 41.3-second, 1080 × 1920 split-screen clip. The running dashboard showed the new layout. All 36 tests passed, including automatic split and Fit fallback coverage.

## Reliability follow-up

- Reproduced the baseline with 36 tests passing and one deprecation warning. Starlette 0.48 referenced AnyIO's deprecated `BlockingPortal` alias. The dashboard startup warning came from pairing Uvicorn 0.35 with WebSockets 17.4.
- Updated and installed FastAPI 0.149.0, Starlette 1.10.0, and Uvicorn 0.53.0 in the workspace environment. Starlette's test client uses HTTPX2. Both services restarted, the dashboard accepted a WebSocket handshake with a non-ASCII header and a 256 MiB upload, and `pip check` found no dependency conflicts.
- Replayed the saved candidate from the zero-export Kai Cenat job. Its hook omitted the required reference, so the campaign rule correctly excluded it. New jobs put exact campaign rejection reasons in their warnings and report, while the dashboard shows required fields before submission.
- Re-ran pytest with deprecation warnings treated as errors. All 37 tests passed.
- Re-ran the live automatic facecam job with the upgraded API. Job `e9768e0241524855b45d697b3f359ea5` completed with a 41.3-second vertical MP4. All seven facecam samples agreed, and the authenticated range download returned HTTP 206.

## V2 Docker and n8n recovery · 25 November 2026

- Started the existing Docker Desktop 4.100.1 installation. The Linux engine pipe reappeared. Verified Docker client and server 29.9.3 and the running Docker WSL 2 distribution. Docker and WSL read checks required access outside the terminal sandbox.
- Started the existing n8n 2.48.8 container. Its original `n8n_data` volume and loopback-only port mapping are in use. The editor and `/healthz` returned 200.
- Started FastAPI and Vite on loopback ports 8000 and 5173. Both Studio URLs returned 200. Vite required access outside the sandbox for esbuild. Verified the Ollama model list includes Qwen 2.5 3B.
- Exported seven live MOMENTRIX definitions to `cache/n8n-recovery-backup-y2iqp4mb/`. The existing hardened workflows had unbound Header Auth and obsolete stage routes. The connection test omitted the rotated token. Updated the local templates to use the existing workflow IDs, the current V2 start and status endpoints, and separate Header Auth credentials.
- Verified Docker-to-FastAPI health gave 401 without authentication and 200 with the existing rotated token. The repaired n8n connection-test HTTP node and assertion ran successfully in a disposable n8n profile. The three targeted backend session, callback replay and webhook receipt tests passed.
- Confirmed the live connection-test workflow has a published definition with the expected GET path. Two disposable production checks still returned 404, including after confirming a published definition. This isolates the unresolved failure to webhook registration or activation, before the authenticated HTTP Request node.
- Generated separate n8n webhook and service tokens in local `.env`. The already-running backend will load them at its next restart. The n8n management API and MCP requests returned 401 without credentials. Live credential binding, publication, n8n execution diagnostics and the complete generation-to-export run remain pending. See [N8N_INTEGRATION.md](N8N_INTEGRATION.md).

## Live n8n and approved export verification · 25 November 2026

- Used the authenticated n8n public API to back up the existing definitions to `cache/n8n-live-api-backup-br856quu/`. Two historical hardened Error Handler executions failed authorization at **Report failure**. Updated and published the existing generation, error and connection-test IDs, and created the previously absent review and export workflow once. Bound distinct Header Auth credentials.
- The connection test became reachable after reactivation and a short interval. It returned HTTP 403 without the credential and HTTP 200 with it. Studio and the frontend proxy used local ports 8000 and 5173.
- Playwright passed the real upload-to-export test in 3.1 minutes. Studio uploaded the synthetic sample and created run `f69eb0c8206c4b1592cc3c7a1771744b`, n8n execution `8` and worker job `b21320c7bfb5446799a463810f57ffdc`. The worker transcribed 108 word timestamps without a cache hit, recorded 11 media events and produced one clip without warnings in 143.94 seconds.
- Before approval, the final download returned HTTP 409. After approving the synthetic test clip, the browser requested task `743f69d89cf541e495f9a64c4c5a502d` and downloaded bytes with HTTP 206. The checked export was available about 23.49 seconds after request creation. FFprobe verified a 41.30-second 1080 × 1920, 30 FPS H.264/AAC MP4. Its SRT contained 26 in-bounds cues. Source and export audio aligned within the sampled speech window, with measured offset 0.0 ms.
- Studio's connection check verifies the authenticated production webhook. Eight targeted Python tests and all three Vitest tests passed, and the React production build succeeded. A separate Playwright desktop and mobile run passed in 23.8 seconds after the assertion was changed to wait for the actual n8n response.
- Registered `n8n-local` in Codex and started OAuth with workflow and execution read scopes. Owner consent and MCP tool discovery remain pending.
- After owner consent, Codex confirmed OAuth and discovered 18 n8n tools. A live MCP workflow search found eight MOMENTRIX workflows. The active hardened generation, hardened error handler, and review/export workflows are enabled for MCP.

## CPU presets and tracked framing · 25 November 2026

- Added Fast, Balanced and Quality presets to Studio. The selected preset persists with each V2 run and controls frame sampling, Whisper beam size, and final FFmpeg encoding. Each preset reuses the installed models. Existing jobs and Balanced transcript cache entries can still be read. Asset analysis is cached by its sampling settings. Layout recommendations use the current project's content type.
- All 70 Python tests passed after the preset change. The production React build and three Vitest tests passed. Both live Edge tests passed in 1.6 minutes with Fast selected. Production n8n execution `15` led to worker job `93feadfc744a49dca924f77b9df439f5`, which used beam 1 and 15 samples and finished in 76.22 seconds with a fresh transcript. The approved export was 41.30 seconds, 1080 × 1920 at 30 FPS, with 26 SRT cues. Browser range download returned HTTP 206.
- Compared all three presets on the installed CPU using the same synthetic speech source and an 8-second export. Whisper was freshly loaded for each run. These one-run stage measurements exclude Ollama and upload time.

| Preset | Sampled frames | Visual analysis | Whisper | Checked 8-second render |
| --- | ---: | ---: | ---: | ---: |
| Fast | 15 | 1.24 s | 3.48 s | 1.96 s |
| Balanced | 30 | 1.47 s | 3.16 s | 3.51 s |
| Quality | 58 | 4.39 s | 7.41 s | 4.52 s |

- Added Follow tracked face and a layout that switches between full frame and a portrait crop during sustained tracking coverage. These render from the selected face samples using source time, so removing a section preserves positioning for the remaining footage. The renderer uses full-frame padding when the track is too short or unreliable, and the editor reports that fallback.
- The 28 focused editing and analysis tests passed, including real FFmpeg checks for tracked framing, full-frame transitions, a jump cut, and fallback. The React build and three Vitest tests passed again.
- The Quality facecam browser test passed in 3.1 minutes. n8n execution `17` generated a clip in 110.74 seconds with 58 visual samples and Whisper beam 5. Studio saved revision 2 with a selected face track and karaoke captions, rendered a 360 × 640 tracked preview, enforced approval and downloaded the approved final with HTTP 206.
- FFprobe verified a 41.30-second 1080 × 1920, 30 FPS H.264/AAC final. Its render report confirms tracked framing. The ASS file contains 108 karaoke timing tags and all 26 SRT cues fit the clip. A sampled speech window aligned at 0.0 ms measured offset. The final render report was available 53.42 seconds after the export request.
- The complete Python suite passed all 73 tests in 70.68 seconds with deprecation warnings treated as errors.

## Metadata, optional schedules, and large media · 25 November 2026

- Added local publishing metadata suggestions and manual fields for title, hook, description, platform captions, hashtags, and thumbnail text. The editor saves changes as a new revision and requires approval before exporting it. The metadata package follows the approved revision.
- Upgraded SQLite to `0002_clip_metadata` using the verified online backup `data/backups/before-0002_clip_metadata-5a330d0b37bb47e5a69b56fc17ba694d.sqlite3`. The previous schema and upgraded database both passed SQLite integrity checks.
- Scheduled ingestion queues a durable scan, checks an explicit allowlist, deduplicates file contents, and reports results on Studio's Automation page. The actual isolated backend imported an allowlisted sample once, reported one duplicate on repeat, and left an unlisted sample untouched. Automatic generation was disabled during the test.
- Imported and published shortened copies of both schedule workflows in a disposable n8n 2.48.8 profile. The timer calls produced three real maintenance diagnostics and one deduplicated scan. The scan waited behind the media task and completed with an empty allowlist. The optional schedules in the main n8n instance remain inactive.
- Streamed exactly 2,147,483,648 bytes to the isolated V2 upload endpoint using a 12-minute synthetic MP4. It returned HTTP 201 after 49.98 seconds, and FFprobe reported a 720-second source. The preview endpoint returned partial bytes with HTTP 206. The 2 GiB payload included MP4 padding to exercise transfer size. Source fixtures and large temporary test files were kept apart from user assets.
- Added the [Windows run guide](RUN_GUIDE.md) and started the production site successfully using its documented command.
- The production-site test uploaded the 12-minute synthetic video and started n8n execution `20`. The generation job `1847c769f76b4be2b85503f6d20abf37` took 140.25 seconds and sampled 180 frames. Windows reported a peak Python backend working set of 625.3 MiB during the test. Ollama and FFmpeg run as separate processes.
- The first browser attempt reached review but timed out on the large metadata response. The worker later rejected that response. Switched to a compact local Ollama request and built platform captions from its short copy. The evidence excerpt comes directly from the saved edit. The focused browser retest passed in 1.1 minutes after loading the existing clip from the same run.
- The retest requested a real Ollama suggestion, applied and edited the copy, and approved revision 2 after rendering its preview. The export metadata contains the edited title, Instagram and TikTok captions, and thumbnail text. The final download returned HTTP 206. FFprobe verified a 41.30-second 1080 × 1920 30 FPS H.264/AAC MP4 and all 26 SRT cues were in bounds. The final export report was ready 6.64 seconds after the request.
- Verified the authenticated metadata ZIP endpoint. It returned HTTP 200 and six files, including the edited revision's metadata and subtitles. All 56 Python unit tests, 20 integration tests, and 5 Vitest tests passed. The React production build and `pip check` passed.

## 25 November 2026 · Master-prompt recovery continuation

- Recovered the workspace without rebuilding or replacing the application.
- Docker Desktop reports engine 29.9.3 and the existing `n8n` container is running and mapped to `127.0.0.1:5678`.
- Ollama is running and `qwen2.5:3b` is installed.
- The FastAPI backend and React Studio are running. FFmpeg, FFprobe, Faster-Whisper and the `base.en` model are available.
- The n8n production connection webhook returned `{"status":"ok"}`.
- The n8n container reached authenticated FastAPI health through `host.docker.internal:8000` and received `{"status":"ok"}`.
- n8n discovery found four active MOMENTRIX workflows: the connection test, hardened main pipeline, hardened error handler, and review/export workflow.
- The main pipeline and review/export workflows are published and active. The main pipeline links the hardened error workflow.
- Current recovery verification: 56 Python unit tests passed, 20 Python integration tests passed, 5 Vitest tests passed, the React production build passed, and `pip check` found no broken requirements.
- No real-authorized creator footage or campaign-compliance review was added. This remains a human/authorized-source blocker.

## 25 November 2026 · Production runtime launch

- Started the existing MOMENTRIX installation through `scripts\start_website.ps1`.
- The production backend and Studio remained single-instance; no duplicate backend was started.
- FastAPI health returned `ok` and production Studio returned HTTP 200.
- n8n health returned `ok`; Docker reports the existing `n8n` container running.
- Live Playwright desktop/mobile navigation passed in 8.1 seconds.
- The live automation navigation test reached Studio through the local key and verified the authenticated n8n connection response.
