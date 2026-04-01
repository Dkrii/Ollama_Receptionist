param(
    [int]$IntervalSeconds = 20
)

$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')

Write-Host "[watchdog] Running every $IntervalSeconds seconds"

while ($true) {
    $healthy = $false

    try {
        $health = Invoke-RestMethod -Method Get -Uri 'http://localhost:8000/health' -TimeoutSec 5
        if ($health.status -eq 'ok') {
            $healthy = $true
        }
    } catch {
    }

    if (-not $healthy) {
        Write-Host '[watchdog] App unhealthy. Restarting stack...'
        docker compose up -d ollama chroma app | Out-Null
    }

    Start-Sleep -Seconds $IntervalSeconds
}
