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

foreach ($task in $tasks) {
    & $cmdExe /c "`"$schtasksExe`" /Query /TN `"$task`" /FO LIST >nul 2>nul"
    if ($LASTEXITCODE -eq 0) {
        & $schtasksExe /Delete /TN $task /F
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to delete $task. Run PowerShell as Administrator and retry."
        }
        Write-Host "[REMOVED] $task"
    } else {
        Write-Host "[SKIP] $task not found"
    }
}

Write-Host ''
Write-Host 'Kiosk task cleanup complete.'
