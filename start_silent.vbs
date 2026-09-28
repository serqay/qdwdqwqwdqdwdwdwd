Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\AI\start_bot_service.ps1""", 0, False
Set WshShell = Nothing
