[CmdletBinding()]
param([string]$Filename = 'Momentrix sample.mp4', [int]$Count = 3,
      [uri]$BackendUrl = 'http://127.0.0.1:8000', [int]$TimeoutSeconds = 1800,
      [switch]$OpeningHook)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $arguments = @('-m', 'scripts.smoke', '--filename', $Filename, '--count', $Count,
                   '--backend', $BackendUrl.AbsoluteUri, '--timeout', $TimeoutSeconds)
    if ($OpeningHook) { $arguments += '--hook' }
    & '.\.venv\Scripts\python.exe' @arguments
    if ($LASTEXITCODE -ne 0) { throw 'End-to-end smoke test failed. See the job and report.' }
} finally { Pop-Location }
