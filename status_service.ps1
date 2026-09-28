Write-Host "=== AI Bot Service Status ===" -ForegroundColor Cyan

# 1. Telegram Bot
$botProc = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -like "*tg_bot_gen.py*" }
if ($botProc) {
    $p = Get-Process -Id $botProc.ProcessId -ErrorAction SilentlyContinue
    $wsMb = [math]::Round($p.WorkingSet64 / 1MB, 1)
    Write-Host "[OK] Telegram Bot is RUNNING (PID: $($botProc.ProcessId), RAM: $wsMb MB, Priority: $($p.PriorityClass))" -ForegroundColor Green
} else {
    Write-Host "[STOPPED] Telegram Bot is NOT running" -ForegroundColor Red
}

# 2. SD Forge
$tcp = Get-NetTCPConnection -LocalPort 7860 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
if ($tcp) {
    $p = Get-Process -Id $tcp.OwningProcess -ErrorAction SilentlyContinue
    $wsMb = if ($p) { [math]::Round($p.WorkingSet64 / 1MB, 1) } else { "?" }
    Write-Host "[OK] SD Forge API is LISTENING on port 7860 (PID: $($tcp.OwningProcess), RAM: $wsMb MB)" -ForegroundColor Green
} else {
    Write-Host "[STOPPED] SD Forge is NOT listening on port 7860" -ForegroundColor Yellow
}

# 3. Autostart status
$startupDir = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir "AI_Bot_Tray.lnk"
if (Test-Path $shortcutPath) {
    Write-Host "[ENABLED] Windows Autostart shortcut is active in shell:startup" -ForegroundColor Green
} else {
    Write-Host "[DISABLED] Windows Autostart shortcut is NOT installed" -ForegroundColor Gray
}

# 4. GPU Metrics
Write-Host "`n--- GPU Metrics ---" -ForegroundColor Cyan
try {
    $gpu = & nvidia-smi --query-gpu=name,temperature.gpu,fan.speed,power.draw,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>$null
    if ($gpu) {
        $parts = $gpu.Split(",")
        Write-Host "GPU: $($parts[0].Trim()) | Temp: $($parts[1].Trim()) C | Fan: $($parts[2].Trim()) % | Power: $($parts[3].Trim()) W"
        Write-Host "VRAM: $($parts[4].Trim()) MB / $($parts[5].Trim()) MB | GPU Load: $($parts[6].Trim()) %"
    }
} catch {
    Write-Host "Unable to read GPU status via nvidia-smi"
}

Write-Host "=============================" -ForegroundColor Cyan
