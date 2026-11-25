[CmdletBinding()]
param([string]$Filename = 'Momentrix sample.mp4')
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
$wav = $null
$voice = $null
try {
    New-Item -ItemType Directory -Force -Path 'cache' | Out-Null
    $wav = Join-Path (Resolve-Path 'cache') ("synthetic-" + [guid]::NewGuid().ToString('N') + '.wav')
    Add-Type -AssemblyName System.Speech
    $voice = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    $voice.Rate = -1
    $voice.SetOutputToWaveFile($wav)
    $voice.Speak("I almost threw away the smallest experiment I ever built. For weeks, I tried to make a paper bridge strong enough to hold a mug of water. Every design collapsed before I could even let go of the mug. On the last night, I ran out of tape and folded one sheet of paper into an accordion. I set the mug down and it held. Then it held two mugs, then three. My biggest mistake was assuming I needed stronger paper. The folds were doing all the work. Now whenever a project gets stuck, I ask myself what I can change about the shape before I buy anything new.")
    $voice.Dispose()
    $voice = $null
    & '.\.venv\Scripts\python.exe' -m scripts.manage sample --filename $Filename --wav $wav
    if ($LASTEXITCODE -ne 0) { throw 'FFmpeg failed to create the synthetic sample.' }
} finally {
    if ($voice) { $voice.Dispose() }
    if ($wav -and (Test-Path -LiteralPath $wav)) { Remove-Item -LiteralPath $wav }
    Pop-Location
}
