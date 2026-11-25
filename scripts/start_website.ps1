[CmdletBinding()]
param([switch]$Dev)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    if ($Dev) {
        Push-Location frontend
        try {
            if (-not (Test-Path node_modules)) { npm.cmd ci; if ($LASTEXITCODE) { throw 'Website dependency installation failed.' } }
            npm.cmd run dev
            if ($LASTEXITCODE) { throw 'The website development server exited with an error.' }
        } finally { Pop-Location }
    } else {
        if (-not (Test-Path frontend/dist/index.html)) {
            Push-Location frontend
            try {
                if (-not (Test-Path node_modules)) { npm.cmd ci; if ($LASTEXITCODE) { throw 'Website dependency installation failed.' } }
                npm.cmd run build
                if ($LASTEXITCODE) { throw 'Website build failed.' }
            } finally { Pop-Location }
        }
        Write-Host 'MOMENTRIX Studio opens at http://127.0.0.1:8000/studio/'
        & '.\scripts\start_backend.ps1'
    }
} finally { Pop-Location }

