$startupDir = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir "AI_Bot_Service.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item -Path $shortcutPath -Force
    Write-Host "Autostart shortcut removed from Windows Startup."
} else {
    Write-Host "Autostart shortcut was not found in Windows Startup."
}
