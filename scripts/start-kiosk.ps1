$ErrorActionPreference = 'Stop'

Set-Location (Join-Path $PSScriptRoot '..')

Write-Host '[kiosk] Starting containers...'
docker compose up -d ollama chroma app
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to start docker services.'
}

$maxRetries = 120
for ($i = 1; $i -le $maxRetries; $i++) {
    try {
        $health = Invoke-RestMethod -Method Get -Uri 'http://localhost:8000/health' -TimeoutSec 5
        if ($health.status -eq 'ok') {
            Write-Host '[kiosk] App is healthy.'
            exit 0
        }
    } catch {
    }

    Start-Sleep -Seconds 2
}

throw 'Kiosk app did not become healthy in time.'
