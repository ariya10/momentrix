# MOMENTRIX

MOMENTRIX turns an authorized local video into ranked vertical clips. The React Studio sends projects to FastAPI, n8n starts the local worker, Faster-Whisper transcribes the source, and Qwen suggests highlights through Ollama. Review clips in Studio before requesting an FFmpeg export.

## Run MOMENTRIX V2 on Windows

See the [Windows run guide](RUN_GUIDE.md) for the complete startup, login, clip export, and troubleshooting steps.

Run these commands from the `momentrix` folder after installing the prerequisites below. Keep the existing n8n instance running. Its authenticated workflow setup is documented in [N8N_INTEGRATION.md](N8N_INTEGRATION.md).

```powershell
.\scripts\start_website.ps1
```

Open [Studio](http://127.0.0.1:8000/studio/) and use the local key printed by `.\scripts\show_studio_key.ps1` in a second terminal. Use **New Project** to upload or select an authorized video. The default file-size limit is 12 GiB. Open **Automation → Test n8n connection** to verify the live workflow and backend authentication.

Choose a processing preset in the wizard's **Generation** step. All presets use the installed local models and the same default 9:16 output dimensions.

| Preset | Visual analysis defaults | Whisper beam | H.264 encode defaults |
| --- | --- | --- | --- |
| Fast | A sample every 3 seconds, up to 180 | 1 | ultrafast, CRF 25 |
| Balanced | A sample every 1.5 seconds, up to 360 | 3 | veryfast, CRF 21 |
| Quality | A sample every 0.75 seconds, up to 720 | 5 | medium, CRF 18 |

Long sources use wider sample intervals to stay within the frame cap. Actual processing time depends on the footage, the local model workload, and which analysis results are already cached.

In the editor, select **Follow tracked face** or **Switch between full frame and tracked face** under **Vertical layout** when the source has a sampled face track. Select the primary track, save the draft, and render a preview before approving. The render uses full-frame padding if coverage or framing is insufficient. Choose karaoke under **Caption style** for timed word highlighting.

## First run on Windows

Open PowerShell in the `momentrix` folder. The parent folder contains the starter workspace.

```powershell
.\scripts\setup.ps1 -WithDev
.\scripts\check_environment.ps1
```

The setup script uses Python 3.11 and installs packages inside `.venv`. Use `-WithDev` for pytest and the optional dashboard. OpenCV is included for local facecam detection.

Install or reuse these local tools:

- **FFmpeg and FFprobe.** Use a Windows build with libx264 and libass. Put the pair on PATH, unpack the portable build under `cache/tools/<build>/bin/`, or set `MOMENTRIX_FFMPEG` and `MOMENTRIX_FFPROBE` in `.env` to their paths. [FFmpeg Windows downloads](https://ffmpeg.org/download.html#build-windows)
- **Ollama.** Start the local application. If Qwen 2.5 3B is missing, run `ollama pull qwen2.5:3b` to download about 1.9 GB. [Ollama Qwen 2.5 library](https://ollama.com/library/qwen2.5:3b)
- **Faster-Whisper base.en.** Run `.\scripts\download_whisper.ps1` once to download the model into the project cache. Jobs use the local copy. [Faster-Whisper documentation](https://github.com/SYSTRAN/faster-whisper)
- **Docker Desktop and n8n Community Edition.** These are needed for workflow automation. You can start an existing stopped container with `docker start n8n` if it is named `n8n`.

To use the legacy V1 Streamlit interface, start the backend in one PowerShell window and the dashboard in another.

```powershell
.\scripts\start_backend.ps1
.\scripts\start_dashboard.ps1
```

Open the dashboard at `http://127.0.0.1:8501`. The backend listens on `http://127.0.0.1:8000` by default. If PowerShell policy blocks scripts, the Python entry points can run directly once the virtual environment exists.

If either startup script reports an existing service, open the dashboard and use the existing session.

```powershell
.\.venv\Scripts\python.exe -m scripts.serve
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.address 127.0.0.1
```

## Create and review a job

1. Place a video you are authorized to use in `input/`, or upload it through the dashboard. MP4, MOV, MKV, and WEBM are accepted. Dashboard uploads support files around 2 GB. For videos near that size or larger, copy the file to `input/` and choose **Local source** to avoid buffering the upload in memory. The default limit for local source files is 12 GiB.
2. Select a campaign, clip count, duration range, and layout. Confirm source permission. Click **Start processing**.
3. After processing, preview each clip, check the transcript timing against the audio, edit its metadata, and approve or reject it. The score is a subjective ranking of the dialogue. Approving a clip records a local review decision.
4. Download MP4, SRT, and the job’s metadata CSV as needed. The output folder also contains ASS styling, JSON and text metadata, transcript, candidates, and job report.

Use **Fit with padding** to preserve the entire source frame. **Center crop** fills the vertical frame. **Manual region** and **Facecam above gameplay** take pixel coordinates from the source as it appears after applying its rotation metadata. Export profiles change encoding speed and compression while retaining 1080 × 1920. The export settings offer audio normalization, a brief picture fade-in, and an opening hook. Submit a new job to change a burned-in hook.

Choose **Automatic facecam** for recordings with a small, stationary facecam in a corner. MOMENTRIX samples seven frames per selected clip and looks for a consistent frontal face. When it finds one, it puts a fixed crop above the full original frame. The original facecam may also appear in the lower pane. An inconclusive detection uses **Fit with padding** and records a job warning. Check the crop in the preview before approving. API and n8n clients can send `layout: "auto_split"`. An API job may also specify a `gameplay` crop for the lower pane.

### Submit with PowerShell

```powershell
$base = 'http://127.0.0.1:8000'
$headers = @{}
# If .env contains a token, load it without printing it.
if (Test-Path .env) {
    $tokenLine = Get-Content .env | Where-Object { $_ -match '^MOMENTRIX_API_TOKEN=.+$' } | Select-Object -Last 1
    if ($tokenLine) { $headers['X-API-Token'] = ($tokenLine -split '=', 2)[1] }
}
$body = @{
    filename = 'Momentrix sample.mp4'
    campaign = 'default'
    count = 3
    layout = 'fit'
    min_duration = 20
    max_duration = 60
    subtitles = $true
    authorized = $true
} | ConvertTo-Json
$job = Invoke-RestMethod "$base/jobs" -Method Post -Headers $headers -ContentType 'application/json' -Body $body
Invoke-RestMethod "$base/jobs/$($job.job_id)" -Headers $headers
Invoke-RestMethod "$base/jobs/$($job.job_id)/clips" -Headers $headers
```

The API also provides `GET /health`, `GET /system/status`, `GET /jobs`, `POST /jobs/{job_id}/cancel`, and `GET /jobs/{job_id}/clips/{clip_id}/download`. The download endpoint supports HTTP byte ranges. `GET /openapi.json` contains the full API contract. Send `X-API-Token` on each request when a token is configured.

## Connect the existing n8n container

1. Generate a local token with `.\.venv\Scripts\python.exe -m scripts.manage token`. It is written to the ignored `.env` file. Restart the backend after changing the token.
2. Open n8n at `http://localhost:5678`. Import [the workflow JSON](workflows/momentrix_v1.json) via **Import from File**.
3. Create a **Header Auth** credential. Set **Name** to `X-API-Token` and **Value** to the token from `.env`. Select the credential on **Check backend health**, **Create job**, and **Get job status**.
4. Edit **Job configuration**. Use `http://host.docker.internal:8000` as the backend URL in Docker Desktop. Set the filename and campaign and set `authorized` to true after confirming source permission.
5. Run **Execute Workflow**. The workflow waits 30 seconds between polls. The default limits are 120 polls and 60 minutes. A polling timeout leaves the backend job running and gives you its ID.

The default loopback binding can work through Docker Desktop’s host bridge. If it fails on another setup, use `-BindAddress` with a Windows address reachable from the Docker network. The start script requires a token for any non-loopback bind. Keep n8n’s local port mapping. [n8n HTTP Request credentials](https://docs.n8n.io/integrations/builtin/credentials/httprequest/) · [Docker Desktop networking](https://docs.docker.com/desktop/features/networking/networking-how-tos/)

## How the pipeline works

1. **The API queues the job.** SQLite keeps the job’s status and timestamps on disk. A single background worker takes the oldest queued job while API requests remain responsive. Queued jobs survive restart. Interrupted active jobs are marked failed and can be resubmitted.
2. **FFmpeg and Whisper prepare evidence.** FFprobe reads media facts. FFmpeg extracts a temporary mono WAV from the first audio stream. Faster-Whisper produces segment and word timestamps. The cache uses a hash of the source bytes and transcription settings. Default `base.en` uses English, CPU, INT8, voice activity detection, and word timestamps. Set a multilingual model such as `base` for automatic language detection, then download that model explicitly.
3. **Ollama proposes clips.** It sees overlapping windows of about five minutes, with roughly a minute of overlap and a character cap. Python gives each eligible start and end pair an ID. Ollama returns structured JSON with that ID, a quote for evidence, scores, and metadata. Python resolves the ID to exact timestamps, verifies the quote against the timed transcript, rejects overlaps and out-of-range clips, then sorts the remaining candidates. A video may yield fewer clips than requested.
4. **FFmpeg renders and checks each export.** It writes a vertical H.264/AAC MP4 with optional on-frame subtitles and a short hook. Quality checks inspect streams and decode the full export. Job reports record elapsed time and seconds per stage.
5. **A person reviews the clip.** The transcript provides spoken evidence. The review checklist covers creator identity, visual events, source authorization, campaign dates, existing official Shorts, and campaign suitability.

Campaign definitions are JSON files in `campaigns/`. The Kai Cenat preset illustrates user-defined rules. It requires an English clip, a hook reference to Kai Cenat, and `#KAICENAT`. Review current campaign terms before use.

## Test and troubleshoot

```powershell
.\.venv\Scripts\python.exe -m pytest -m 'not integration'
.\.venv\Scripts\python.exe -m pytest -m integration
.\scripts\new_sample.ps1
.\scripts\smoke_test.ps1 -Count 3 -OpeningHook
```

Unit tests mock heavy services. Integration tests render all four layouts with FFmpeg and request a schema-constrained response from the installed Ollama model. The smoke runner submits a real job to the running backend and requires at least one verified download. The sample script generates a speech video locally using an installed Windows Speech voice. You can also pass `-Filename` for a video you are authorized to use.

| Symptom | Check |
| --- | --- |
| FFmpeg or FFprobe is missing | Run the environment script. Check both executable paths and use a build with libx264 and libass. |
| Whisper model is missing | Run the download script and inspect `GET /system/status`. A model folder can also be configured with `MOMENTRIX_WHISPER_MODEL`. |
| Ollama returns no valid selection | Check that Ollama is running locally and that the configured model appears in `ollama list`. The job records failures after bounded retries. |
| No clips were found | Check the dashboard warnings and `output/<job_id>/job_report.json`. They identify missing campaign rules such as a required hook reference or hashtag. Silence, a language mismatch, and weak dialogue evidence can also yield zero clips. |
| n8n gets 401 or 403 | Select the Header Auth credential in all three HTTP nodes and restart the backend after setting its token. |
| n8n cannot connect | Start the existing Docker container and check that the configured host and port reach the Windows backend. |
| Processing uses too much memory or CPU | Choose the low export profile, lower `MOMENTRIX_CPU_THREADS`, or configure a smaller local Whisper model. |
| Cancellation takes time | FFmpeg stops promptly. An in-flight Whisper segment or Ollama request reaches its next cancellation check or timeout first. |

See [PROGRESS.md](PROGRESS.md) for verified results and remaining gaps. Potential later upgrades include visual highlight detection, automatic face tracking, dynamic reframing, animated captions, batch submission, and feedback-based ranking.
