param(
    [string]$Url = 'http://localhost:8000'
)

$edgeCandidates = @(
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
)

$edgePath = $edgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edgePath) {
    throw 'Microsoft Edge not found.'
}

Start-Process -FilePath $edgePath -ArgumentList @(
    '--kiosk',
    $Url,
    '--edge-kiosk-type=fullscreen',
    '--no-first-run',
    '--disable-pinch',
    '--overscroll-history-navigation=0'
)
