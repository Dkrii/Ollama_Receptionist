Set-Location (Join-Path $PSScriptRoot '..')

Write-Host '[kiosk] Stopping browser...'
Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host '[kiosk] Stopping containers...'
docker compose stop app chroma ollama
