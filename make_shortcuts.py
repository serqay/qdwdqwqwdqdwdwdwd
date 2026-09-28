import os
import win32com.client

shell = win32com.client.Dispatch('WScript.Shell')
desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')

exe = r"C:\Users\serqay\AppData\Local\Programs\Python\Python313\pythonw.exe"
args = r'"D:\AI\tray_app.py"'
icon = r"D:\AI\bot_tray_icon.ico,0"

targets = [
    os.path.join(desktop, "AI Bot.lnk"),
    r"D:\AI\AI Bot.lnk"
]

for t in targets:
    sc = shell.CreateShortcut(t)
    sc.TargetPath = exe
    sc.Arguments = args
    sc.WorkingDirectory = r"D:\AI"
    sc.IconLocation = icon
    sc.Description = "AI Bot Tray Service"
    sc.Save()

print("Shortcuts successfully created on Desktop and in D:\\AI")
