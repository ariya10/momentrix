$ErrorActionPreference = 'Stop'
$keyPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'data\studio.key'
if (-not (Test-Path -LiteralPath $keyPath)) { throw 'Start the V2 backend once to create the studio key.' }
Get-Content -Raw -LiteralPath $keyPath

