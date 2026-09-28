$startupDir = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir "AI_Bot_Service.lnk"

$wshShell = New-Object -ComObject WScript.Shell
$shortcut = $wshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"D:\AI\start_silent.vbs`""
$shortcut.WorkingDirectory = "D:\AI"
$shortcut.Description = "Auto-start Telegram Bot and Headless Forge without idle load"
$shortcut.Save()

Write-Host "Autostart shortcut created at: $shortcutPath"
Write-Host "Services will start silently in background upon Windows login."
