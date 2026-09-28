# PowerShell script to start Headless SD Forge and Telegram Bot with zero idle load
$LogFile = "D:\AI\service.log"

function Write-ServiceLog($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

Write-ServiceLog "Initiating background startup..."

# 1. Wait for Internet connection (up to 30 seconds if booting with Windows)
$netReady = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $ip = [System.Net.Dns]::GetHostAddresses("api.telegram.org")
        if ($ip) {
            $netReady = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}

if (-not $netReady) {
    Write-ServiceLog "Warning: Internet connection check timed out, proceeding anyway..."
} else {
    Write-ServiceLog "Network is online."
}

# 2. Check and start SD Forge Headless API (port 7860)
$forgeRunning = $false
try {
    $tcp = Get-NetTCPConnection -LocalPort 7860 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
    if ($tcp) { $forgeRunning = $true }
} catch {}

if (-not $forgeRunning) {
    $existingForge = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -like "*stable-diffusion-webui-forge*" }
    if ($existingForge) { $forgeRunning = $true }
}

if ($forgeRunning) {
    Write-ServiceLog "SD Forge is already active on port 7860."
} else {
    Write-ServiceLog "Starting SD Forge in headless mode (--nowebui, zero idle GPU load)..."
    $forgeBat = "D:\AI\stable-diffusion-webui-forge\webui-headless.bat"
    $forgeProc = Start-Process -FilePath $forgeBat `
        -WorkingDirectory "D:\AI\stable-diffusion-webui-forge" `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 2
    try {
        $fp = Get-Process -Id $forgeProc.Id -ErrorAction SilentlyContinue
        if ($fp) { $fp.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal }
    } catch {}
}

# 3. Check and start Telegram Bot
$botProc = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -like "*tg_bot_gen.py*" }
if ($botProc) {
    Write-ServiceLog "Telegram Bot is already running (PID: $($botProc.ProcessId))."
} else {
    Write-ServiceLog "Starting Telegram Bot (pythonw.exe, zero idle CPU load)..."
    $pythonw = "C:\Users\serqay\AppData\Local\Programs\Python\Python313\pythonw.exe"
    if (-not (Test-Path $pythonw)) {
        $pythonw = "pythonw.exe"
    }
    $bProc = Start-Process -FilePath $pythonw `
        -ArgumentList "`"D:\AI\tg_bot_gen.py`"" `
        -WorkingDirectory "D:\AI" `
        -WindowStyle Hidden `
        -PassThru
    try {
        $bp = Get-Process -Id $bProc.Id -ErrorAction SilentlyContinue
        if ($bp) { $bp.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal }
    } catch {}
    Write-ServiceLog "Telegram Bot launched successfully (PID: $($bProc.Id))."
}

Write-ServiceLog "All services initialized. System is in zero-load standby."
