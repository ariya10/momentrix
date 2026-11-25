[CmdletBinding()]
param([switch]$WithDev)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        py -3.11 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python 3.11 virtual environment.' }
    }
    $requirements = if ($WithDev) { 'requirements-dev.txt' } else { 'requirements.txt' }
    & '.\.venv\Scripts\python.exe' -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
    & '.\.venv\Scripts\python.exe' -m scripts.manage verify
    if ($LASTEXITCODE -ne 0) { throw 'Runtime import verification failed.' }
} finally { Pop-Location }
