[CmdletBinding()]
param([uri]$BackendUrl = 'http://127.0.0.1:8000')
$ErrorActionPreference = 'Continue'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $os = [System.Environment]::OSVersion.VersionString
    Write-Output "Windows: $os"
    Write-Output "Logical processors: $([Environment]::ProcessorCount)"
    $memory = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    if ($memory) { Write-Output "RAM: $([math]::Round($memory.TotalPhysicalMemory / 1GB, 1)) GiB" }
    else {
        try {
            Add-Type -AssemblyName Microsoft.VisualBasic -ErrorAction Stop
            $bytes = [Microsoft.VisualBasic.Devices.ComputerInfo]::new().TotalPhysicalMemory
            Write-Output "RAM: $([math]::Round($bytes / 1GB, 1)) GiB"
        } catch { Write-Output 'RAM could not be read in this session' }
    }
    $gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
    $adapters = if ($gpu) { $gpu.Name }
    else {
        Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*' -ErrorAction SilentlyContinue |
            Where-Object DriverDesc | Select-Object -ExpandProperty DriverDesc -Unique
    }
    if ($adapters) { $adapters | ForEach-Object { Write-Output "Display adapter: $_" } }
    else { Write-Output 'Display adapter could not be read in this session' }
    $drive = [System.IO.DriveInfo]::new((Get-Location).Drive.Root)
    Write-Output "Free disk: $([math]::Round($drive.AvailableFreeSpace / 1GB, 1)) GiB"
    py -3.11 --version
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        docker version --format '{{.Server.Version}}'
        docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'
    }
    try {
        $n8n = Invoke-RestMethod 'http://localhost:5678/healthz' -TimeoutSec 4
        Write-Output "n8n health: $($n8n.status)"
    } catch { Write-Output 'n8n health endpoint unavailable' }
    if (Test-Path '.venv\Scripts\python.exe') {
        & '.\.venv\Scripts\python.exe' -m scripts.status --backend $BackendUrl.AbsoluteUri
    } else { Write-Output 'Run scripts/setup.ps1 to create the workspace Python environment.' }
} finally { Pop-Location }
