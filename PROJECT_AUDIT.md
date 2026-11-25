# MOMENTRIX Project Audit

Audit date: 24 November 2026

## Current structure

- `app/` - FastAPI application, V1 pipeline, persistent worker, V2 project/run APIs.
- `frontend/` - React 19 and Vite 7 MOMENTRIX studio.
- `backend/migrations/versions/` - additive SQLite/Alembic migration.
- `dashboard/app.py` - preserved V1 Streamlit interface.
- `automation/workflows/` - n8n workflow exports.
- `workflows/` - legacy V1 workflow.
- `tests/` - Python unit and integration coverage.
- `data/jobs.sqlite3` - persistent jobs and V2 tables.

## Verified working

- Python 3.11 virtual environment and dependencies: `pip check` passed.
- Backend unit suite: 50 tests passed.
- Backend integration suite: 16 tests passed.
- React production build: TypeScript and Vite build passed.
- SQLite integrity: `ok`; 9 existing jobs before the audit.
- SQLite audit backup created at `data/backups/audit-backup-20261124-145057.sqlite3` and passed integrity.
- V2 migration, browser session separation, asset validation, project/run persistence, campaign validation, webhook credentials, and run replay/deduplication are implemented and tested.
- V1 API and worker behavior, FFmpeg layouts, facecam detection, editing, and review behavior are represented in tests.

## Incomplete features

- Playwright login and navigation smoke coverage exists in `frontend/e2e/studio.spec.ts`.
- There is no explicit 16:9/9:16 browser preview workflow audit of every page.
- n8n has workflow exports, but live activation and credentials require user approval.
- Audio/visual evidence analysis exists only as partial V2 modules and tests; creator-quality ranking is not fully proven.
- Advanced continuous face tracking and dynamic reframing are not established by real-media evidence.
- Animated subtitle styles and a browser EDL workflow are not complete as a release-verified feature set.
- A persistent metrics/operations dashboard exists at API level, but frontend coverage is not all proven.

## Known bugs

- `npm test` fails with exit code 1 because no `src/**/*.test.{ts,tsx}` files are configured or present.
- Streamlit remains as a legacy dashboard. It is not the V2 runtime, but it must be clearly marked as V1 compatibility.
- The Pasted master prompt is broader than the checked-in implementation and includes several target features that need measured verification.

## Missing dependencies

- No missing Python dependencies were reported by `pip check`.
- The environment can build and run the React frontend.
- n8n activation credentials are intentionally absent.
- Browser test coverage is missing, not a package dependency.

## Integration problems

- V2 run dispatch requires n8n credentials and an approved production webhook.
- Legacy `/jobs` endpoints must remain separate from V2 authenticated website sessions.
- V1 and V2 output paths share storage and must continue to preserve historical media.

## Security issues

- Studio key and service credentials must stay outside source control and separate.
- Publishing and campaign submission are intentionally not implemented in V1/V2 pipelines.
- Live n8n activation should not occur without explicit approval.

## Implementation order

1. Close verified frontend test and browser coverage gaps.
2. Stabilize live n8n connection test and approved workflow activation.
3. Complete project wizard upload and real generation progress surfaces.
4. Prove audio/scene/motion evidence and ranking on authorized real media.
5. Complete stable face tracking and dynamic reframing.
6. Complete browser editing EDL, preview, review, and approved export.
7. Add operations metrics, storage, failure, and maintenance verification.
8. Run release browser, real-media, n8n, and backend integration tests.

