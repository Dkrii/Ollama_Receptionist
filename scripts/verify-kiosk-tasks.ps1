$ErrorActionPreference = 'Stop'
$schtasksExe = 'C:\Windows\System32\schtasks.exe'
$cmdExe = 'C:\Windows\System32\cmd.exe'
if (-not (Test-Path $schtasksExe)) {
    throw 'schtasks.exe not found on this machine.'
}
if (-not (Test-Path $cmdExe)) {
    throw 'cmd.exe not found on this machine.'
}

$tasks = @(
    'Kiosk-StartStack',
    'Kiosk-LaunchUI',
    'Kiosk-Watchdog'
)

$missing = @()

foreach ($task in $tasks) {
    & $cmdExe /c "`"$schtasksExe`" /Query /TN `"$task`" /FO LIST >nul 2>nul"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] $task"
    } else {
        Write-Host "[MISSING] $task"
        $missing += $task
    }
}

if ($missing.Count -gt 0) {
    Write-Host ''
    Write-Host 'Some tasks are missing. If this machine is locked down, run as Administrator:'
    Write-Host 'powershell -ExecutionPolicy Bypass -File .\scripts\register-kiosk-tasks.ps1'
    exit 1
}

Write-Host ''
Write-Host 'All kiosk tasks are registered.'
