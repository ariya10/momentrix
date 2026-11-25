# MOMENTRIX Known Issues

## Frontend testing

The production-site browser tests used authorized synthetic samples, including a 12-minute video. Representative creator footage and campaign compliance still need verification.

## n8n

The production connection webhook briefly returned HTTP 404 after publication and reactivation. The following authenticated request succeeded, and generation and reviewed export passed. Check the production URL after publication. Codex MCP OAuth is working with workflow and execution read scopes. [Setup and recovery details](N8N_INTEGRATION.md)

Docker Desktop and the existing n8n container had stopped. The container's configured restart policy is `no`. Both are running as of the recovery check.

## Runtime verification

The local integration suite verifies real FFmpeg and Ollama processing. Studio processed a 12-minute synthetic video, and an isolated V2 backend accepted an exact 2 GiB streaming upload. Long creator footage and whole-system memory on that footage still need representative verification.

## Legacy UI

Streamlit is retained for V1 compatibility. The V2 runtime is React on `/studio/`; Streamlit is not the target V2 interface.

## Advanced features

Face-follow and context switching are based on sampled face locations. Real FFmpeg tests cover both layouts, timing after cuts, and full-frame fallback. Verify framing manually on footage with multiple faces, occlusion, or sparse tracking coverage. Ollama metadata is a suggestion for review. Scheduled ingestion remains opt-in with an explicit allowlist.

