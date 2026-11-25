[CmdletBinding()]
param([string]$BindAddress = '127.0.0.1', [ValidateRange(1,65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & '.\.venv\Scripts\python.exe' -m scripts.serve --host $BindAddress --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Backend exited with an error.' }
} finally { Pop-Location }
