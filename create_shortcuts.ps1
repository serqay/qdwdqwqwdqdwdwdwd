$wsh = New-Object -ComObject WScript.Shell

# 1. Shortcut in D:\AI
$scPath = "D:\AI\Запустить бота (Трей).lnk"
$sc = $wsh.CreateShortcut($scPath)
$sc.TargetPath = "C:\Users\serqay\AppData\Local\Programs\Python\Python313\pythonw.exe"
$sc.Arguments = "`"D:\AI\tray_app.py`""
$sc.WorkingDirectory = "D:\AI"
$sc.IconLocation = "D:\AI\bot_tray_icon.ico,0"
$sc.Description = "Запуск Telegram бота и SD Forge в трей"
$sc.Save()

# 2. Update Startup folder
$startupDir = [System.Environment]::GetFolderPath('Startup')
$scStartup = $wsh.CreateShortcut((Join-Path $startupDir "AI_Bot_Tray.lnk"))
$scStartup.TargetPath = "C:\Users\serqay\AppData\Local\Programs\Python\Python313\pythonw.exe"
$scStartup.Arguments = "`"D:\AI\tray_app.py`""
$scStartup.WorkingDirectory = "D:\AI"
$scStartup.IconLocation = "D:\AI\bot_tray_icon.ico,0"
$scStartup.Description = "AI Bot Tray Service"
$scStartup.Save()

# Remove old shortcut if present
$old = Join-Path $startupDir "AI_Bot_Service.lnk"
if (Test-Path $old) { Remove-Item $old -Force }

Write-Host "All shortcuts created successfully."
