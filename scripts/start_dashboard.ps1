[CmdletBinding()]
param([ValidateRange(1,65535)][int]$Port = 8501)
$ErrorActionPreference = 'Stop'
$dashboardUrl = "http://127.0.0.1:$Port"
try {
    $health = Invoke-WebRequest -Uri "$dashboardUrl/_stcore/health" -UseBasicParsing -TimeoutSec 2 -MaximumRedirection 0
} catch {
    $health = $null
}
if ($health -and $health.StatusCode -eq 200 -and $health.Content -eq 'ok') {
    Write-Output "A Streamlit dashboard is already running at $dashboardUrl. Open that address to use it."
    return
}

Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & '.\.venv\Scripts\python.exe' -m streamlit run 'dashboard/app.py' --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard exited with an error.' }
} finally { Pop-Location }
