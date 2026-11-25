[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:HF_HUB_DISABLE_XET = '1'
    & '.\.venv\Scripts\python.exe' -m scripts.manage whisper
    if ($LASTEXITCODE -ne 0) { throw 'Whisper model download failed.' }
} finally { Pop-Location }
