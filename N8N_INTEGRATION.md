# MOMENTRIX V2 and n8n

## Recovery on 25 November 2026

Docker Desktop 4.100.1 was stopped. Starting the existing per-user installation restored Docker 29.9.3 on the `docker-desktop` WSL 2 distribution. The existing `n8n` container runs version 2.48.8, mounts `n8n_data` at `/home/node/.n8n`, and publishes `127.0.0.1:5678`.

Seven live MOMENTRIX workflow definitions were exported before editing. The original CLI backup is at `cache/n8n-recovery-backup-y2iqp4mb/`, and the pre-change REST backup is at `cache/n8n-live-api-backup-br856quu/`.

The first request after publishing and the first request after reactivation both returned 404. A subsequent request succeeded. The production connection test returned 403 without its webhook credential and 200 with it. The authenticated test reached FastAPI through `host.docker.internal:8000`.

Studio uploaded the authorized synthetic sample and started n8n execution `8`. The worker performed fresh Whisper transcription, analyzed local media, selected a clip with Qwen and reached human review. Playwright verified export was blocked before approval. It then approved the test clip, requested the export, and verified the authenticated MP4 download returned HTTP 206. Generation took 143.94 seconds. The approved export took about 23.49 seconds from request to the checked render report. FFprobe verified 1080 × 1920, 30 FPS, H.264/AAC and 41.30 seconds. All 26 SRT cues were within the clip, and a sampled speech window had a measured 0.0 ms offset.

## Administrative access

The n8n REST API accepted the management key and confirmed the earlier Error Handler authorization failures at the **Report failure** HTTP node. MCP is served separately at `http://localhost:5678/mcp-server/http`. Codex is connected as `n8n-local` using OAuth with `workflow:read` and `execution:read`. The authenticated MCP search found eight MOMENTRIX workflows. The active hardened generation, hardened error handler and review/export workflows are enabled for MCP. The active backend connection test appears in search and is currently disabled for MCP access.

1. Open [local n8n](http://localhost:5678) and sign in as the owner.
2. For the REST API, open **Settings → n8n API → Create an API key**. Select the shortest useful expiry. Start with workflow and execution read scopes when offered. Add workflow update and activation scopes for the repairs. Keep the key locally in `N8N_API_KEY`, with `N8N_API_URL=http://127.0.0.1:5678/api/v1`. Use the `X-N8N-API-KEY` header. [n8n REST authentication](https://docs.n8n.io/connect/n8n-api/authentication/)
3. For MCP, open **Settings → Instance-level MCP** and enable access if desired. Open **Connect a client** and confirm the server URL ends in `/mcp-server/http`. Choose the supported access-token option if offered and keep the token locally in `N8N_MCP_TOKEN`. Select only the workflows intended for Codex. Codex MCP configuration requires your approval. [n8n instance MCP documentation](https://docs.n8n.io/connect/connect-to-n8n-mcp-server/)

## Configure Header Auth credentials

The three workspace values are in the ignored `.env`. In n8n, create or reuse one **Header Auth** credential per row. Enter the value directly from the local file into n8n. Keep each credential separate from the n8n REST key and MCP token.

| Credential use | Header name | Value in `.env` |
| --- | --- | --- |
| FastAPI health in the connection test | `X-API-Token` | `MOMENTRIX_API_TOKEN` |
| Generation and export webhook triggers, and the diagnostic webhook | `X-Momentrix-Webhook` | `MOMENTRIX_WEBHOOK_SECRET` |
| HTTP Request nodes calling `/api/v2/internal/...` | `X-Momentrix-Service` | `MOMENTRIX_SERVICE_TOKEN` |

Restart the FastAPI backend after configuring the n8n credentials so it reads the new local values. Vite can remain running.

## Published workflows and repair instructions

Update each existing workflow by ID. To do this with the editor, open the target from **Overview → Workflows**, copy or export its draft, remove the old nodes from that workflow canvas, then use the editor's **… → Import from File** to load the matching JSON. Save the draft in the same workflow. If n8n opens the import as a separate workflow, close that draft and copy the imported nodes to the existing workflow instead. Select the credentials and verify the final settings before choosing **Publish**.

| Workflow | Existing ID | Local definition |
| --- | --- | --- |
| Backend Connection Test | `MtrxV2ConnectionTest` | [00_connection_test.json](automation/workflows/00_connection_test.json) |
| Main Pipeline - Hardened | `m1NWPdRGRggdhFDv` | [01_generation_orchestrator.json](automation/workflows/01_generation_orchestrator.json) |
| Error Handler - Hardened | `ttCvGQYy2llJ1gd3` | [02_error_handler.json](automation/workflows/02_error_handler.json) |
| Review and export | `PycBl0vAR4EvTEUk` | [04_review_and_export.json](automation/workflows/04_review_and_export.json) |

1. Select webhook Header Auth on **Connection test webhook** and API Token Header Auth on **Check FastAPI health**. Publish, open the node's **Production URL** tab, and send an authenticated GET with `X-Momentrix-Webhook` to `http://127.0.0.1:5678/webhook/momentrix/v2/connection-test`. The expected body is `{"status":"ok"}`. If it still returns 404, record any publish or activation error from the workflow editor and resolve that before publishing the generation workflow.
2. Configure **Error Handler - Hardened** first. Select the service credential on its HTTP Request nodes. Save and publish its callable version so the generation and export workflows can invoke it.
3. In the **Main Pipeline - Hardened** and **Review and export** workflows, select the webhook credential on the trigger and service credential on the HTTP Request nodes. In each **Record monitoring timeout** node, select **Error Handler - Hardened**. Set the same workflow under the workflow's **Settings → Error workflow**. Publish after reviewing the production paths `momentrix/v2/generate` and `momentrix/v2/export`.
4. Optional schedules are [03_scheduled_ingestion.json](automation/workflows/03_scheduled_ingestion.json) and [05_maintenance.json](automation/workflows/05_maintenance.json). Configure authorized filenames before publishing scheduled ingestion.

Scheduled ingestion accepts an allowlist and queues one scan at a time. The POST returns a persisted task with HTTP 202. Studio's **Automation** page reports the imports, duplicates, and file errors after the worker finishes. Automatic generation is a separate opt-in setting. Maintenance reports disk space, pending work, interrupted jobs, and transcript cache size. [Schedule setup](RUN_GUIDE.md#optional-scheduled-ingestion-and-maintenance) · [n8n Schedule Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/)

After the connection test succeeds on its production URL, submit the authorized synthetic `input/Momentrix sample.mp4` in [React Studio](http://127.0.0.1:5173/studio/). Verify the n8n execution, the backend run, timestamps and preview, then review and request the final export. Record elapsed time and FFprobe results in PROGRESS.md.

In Studio, **Automation → Test n8n connection** checks n8n health and the authenticated production connection-test webhook. A reachable server with an unregistered or misconfigured webhook shows **Unverified**.
