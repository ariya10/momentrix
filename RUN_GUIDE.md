# Run MOMENTRIX V2 on Windows

## Start your existing installation

1. Open **Docker Desktop** from the Windows Start menu and wait for its Linux engine. Open **Ollama** if it is stopped.
2. Open PowerShell and run the commands below. Keep this window open while using Studio.

   ```powershell
   Set-Location 'D:\Downloads\momentrix-starter\momentrix'
   docker start n8n
   .\scripts\start_website.ps1
   ```

3. Open [MOMENTRIX Studio](http://127.0.0.1:8000/studio/). Open a second PowerShell window for the Studio key.

   ```powershell
   Set-Location 'D:\Downloads\momentrix-starter\momentrix'
   .\scripts\show_studio_key.ps1
   ```

4. Paste the key into Studio. Open **Automation → Test n8n connection**. A working connection displays **Connected**.

The production site uses port 8000. To run in development mode, keep the backend running and run `.\scripts\start_website.ps1 -Dev` in a second PowerShell window. The development address is [Studio on port 5173](http://127.0.0.1:5173/studio/).

## Set up a new workspace

Install Python 3.11, Node.js 22.12 or newer, Docker Desktop, and Ollama. Keep the existing self-hosted n8n container if you have one. Use FFmpeg and FFprobe with H.264 and libass support, either on PATH or in the workspace portable tools directory. [Prerequisite details](README.md)

```powershell
Set-Location 'D:\Downloads\momentrix-starter\momentrix'
.\scripts\setup.ps1
ollama pull qwen2.5:3b
.\scripts\download_whisper.ps1
.\.venv\Scripts\python.exe -m scripts.manage token
.\.venv\Scripts\python.exe -m scripts.manage n8n-credentials
.\scripts\check_environment.ps1
```

The model commands download files if they are missing. Configure and publish the required n8n workflows using the existing workflow IDs and the three separate Header Auth credentials. [n8n setup and credential mappings](N8N_INTEGRATION.md)

## Generate and export a clip

1. In Studio, open **New Project**. Upload a video or put it in `input/` and choose **Local folder**. Confirm you have permission to process it.
2. Choose a campaign, clip count, processing preset, and layout. Start automation and follow the run on its project page. The current default limits are 12 GiB per file and four hours of source duration.
3. Open the clip editor. Adjust trims, framing or captions. Expand **Publishing metadata** to edit the platform fields or request a local suggestion from Ollama. Read the evidence, choose **Use suggestion** if it fits, and save the draft.
4. Render a preview of the saved draft. Review the source permission, campaign rules, clip and metadata. Click **Approve**, then **Export final** and **Download final MP4**. The Clip Library can also export selected approved clips.

Saved changes start a new revision that needs review. Rendered MP4s and approved export packages are under `storage\exports\`. The app writes local files for you to review and distribute.

## Optional scheduled ingestion and maintenance

Leave these workflows inactive unless you want scheduled runs. They use the same n8n **MOMENTRIX V2 Backend Service** Header Auth credential as the production pipeline.

1. Add the exact authorized filenames to the workspace's existing `.env`. Use a JSON array and put those files in `input/`.

   ```dotenv
   MOMENTRIX_SCHEDULED_FILENAMES=["Authorized sample.mp4"]
   MOMENTRIX_SCHEDULED_AUTO_PROCESS=false
   MOMENTRIX_SCHEDULED_CAMPAIGN=default
   ```

2. Import [Scheduled ingestion](automation/workflows/03_scheduled_ingestion.json) and/or [Maintenance](automation/workflows/05_maintenance.json) once. Select the service credential on each HTTP Request node and the existing hardened error handler in workflow settings. Review the schedule trigger, then publish whichever workflow you want to enable.
3. Restart the backend after editing `.env`. Studio's **Automation** page shows the latest scheduled scan. Files are deduplicated by content. Set `MOMENTRIX_SCHEDULED_AUTO_PROCESS=true` only when you want the allowlisted scheduled imports sent for clip generation. The maintenance workflow reports workspace health and disk usage.

## If startup fails

| Symptom | Check |
| --- | --- |
| `cd start_backend.ps1` fails | Change to the `momentrix` directory and run `.\scripts\start_website.ps1`. A `.ps1` file is a script. |
| PowerShell blocks script execution | Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_website.ps1` from `momentrix`. This applies to that invocation. |
| The backend reports an existing worker | Use [the current Studio](http://127.0.0.1:8000/studio/). For a restart, stop the existing backend in its own terminal with **Ctrl+C** once jobs finish. |
| Docker reports a missing Linux engine pipe | Open Docker Desktop and wait until `docker version` shows both client and server. Then run `docker start n8n`. |
| Studio shows n8n as unverified | Open [n8n](http://localhost:5678). Check the published connection-test workflow and its credentials. Use the local values from `.env`. [n8n troubleshooting](N8N_INTEGRATION.md) |
| Whisper, Ollama or FFmpeg is unavailable | Run `.\scripts\check_environment.ps1` and check **Settings** in Studio. See prerequisites above. |
| You see the legacy dashboard or port 8501 | Open [React Studio on port 8000](http://127.0.0.1:8000/studio/). The legacy dashboard is a separate V1 entry point. |
