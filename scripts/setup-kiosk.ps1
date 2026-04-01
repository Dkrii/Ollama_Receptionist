param(
    [switch]$SkipTaskRegistration,
    [switch]$SkipModelPull,
    [switch]$SkipReindex,
    [switch]$SkipLaunch,
    [string]$KioskUrl = 'http://localhost:8000'
)

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

$startScript = Join-Path $root 'scripts\start-kiosk.ps1'
$launchScript = Join-Path $root 'scripts\launch-kiosk.ps1'
$registerScript = Join-Path $root 'scripts\register-kiosk-tasks.ps1'
$verifyScript = Join-Path $root 'scripts\verify-kiosk-tasks.ps1'

Write-Host '[setup] Starting stack and waiting for health...'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to start stack.'
}

if (-not $SkipModelPull) {
    Write-Host '[setup] Pulling Ollama models (qwen2.5:3b + nomic-embed-text)...'
    docker compose run --rm init-model
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to pull Ollama models.'
    }
}

if (-not $SkipReindex) {
    Write-Host '[setup] Reindexing knowledge base...'
    Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/reindex' -TimeoutSec 180 | Out-Null
}

if (-not $SkipTaskRegistration) {
    Write-Host '[setup] Registering startup tasks...'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $registerScript
    if ($LASTEXITCODE -ne 0) {
        throw 'Task registration failed. Run this script from PowerShell as Administrator or use -SkipTaskRegistration.'
    }

    Write-Host '[setup] Verifying startup tasks...'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $verifyScript
    if ($LASTEXITCODE -ne 0) {
        throw 'Task verification failed after registration.'
    }
} else {
    Write-Host '[setup] Skipping task registration by request.'
}

if (-not $SkipLaunch) {
    Write-Host '[setup] Launching kiosk browser...'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launchScript -Url $KioskUrl
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to launch kiosk browser.'
    }
} else {
    Write-Host '[setup] Skipping browser launch by request.'
}

Write-Host ''
Write-Host '[setup] Kiosk provisioning complete.'
