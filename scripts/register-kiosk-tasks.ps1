$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$startScript = Join-Path $root 'scripts\start-kiosk.ps1'
$launchScript = Join-Path $root 'scripts\launch-kiosk.ps1'
$watchdogScript = Join-Path $root 'scripts\watchdog-kiosk.ps1'

$ErrorActionPreference = 'Stop'
$schtasksExe = 'C:\Windows\System32\schtasks.exe'
if (-not (Test-Path $schtasksExe)) {
	throw 'schtasks.exe not found on this machine.'
}

$startCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`""
$launchCmd = "cmd.exe /c timeout /t 12 /nobreak >nul & powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$launchScript`""
$watchdogCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`""
$verifyScript = Join-Path $root 'scripts\verify-kiosk-tasks.ps1'

& $schtasksExe /Create /F /TN "Kiosk-StartStack" /SC ONLOGON /TR $startCmd
if ($LASTEXITCODE -ne 0) {
	throw 'Failed to create Kiosk-StartStack. Run PowerShell as Administrator and retry.'
}

& $schtasksExe /Create /F /TN "Kiosk-LaunchUI" /SC ONLOGON /TR $launchCmd
if ($LASTEXITCODE -ne 0) {
	throw 'Failed to create Kiosk-LaunchUI. Run PowerShell as Administrator and retry.'
}

& $schtasksExe /Create /F /TN "Kiosk-Watchdog" /SC ONLOGON /TR $watchdogCmd
if ($LASTEXITCODE -ne 0) {
	throw 'Failed to create Kiosk-Watchdog. Run PowerShell as Administrator and retry.'
}

Write-Host 'Tasks registered:'
Write-Host '- Kiosk-StartStack'
Write-Host '- Kiosk-LaunchUI'
Write-Host '- Kiosk-Watchdog'

if (Test-Path $verifyScript) {
	Write-Host ''
	Write-Host 'Verification result:'
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File $verifyScript
}
