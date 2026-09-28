# Notify via Telegram
$configPath = "D:\AI\tg_config.json"
if (Test-Path $configPath) {
    try {
        $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($cfg.bot_token -and $cfg.chat_id) {
            $ts = Get-Date -Format "dd.MM.yyyy HH:mm:ss"
            $msg = "<b>Bot stopped.</b>`n`nTime: $ts"
            $body = @{ chat_id = $cfg.chat_id; text = $msg; parse_mode = "HTML" } | ConvertTo-Json
            Invoke-RestMethod -Uri "https://api.telegram.org/bot$($cfg.bot_token)/sendMessage" -Method Post -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 5 -ErrorAction SilentlyContinue | Out-Null
        }
    } catch {}
}

# Stop Tray App Supervisor first (to prevent auto-respawn)
$trayProcs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -like "*tray_app.py*" }
foreach ($p in $trayProcs) {
    Write-Host "Stopping Tray App Supervisor (PID $($p.ProcessId))..."
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# Stop Telegram Bot
$botProcs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -like "*tg_bot_gen.py*" }
foreach ($p in $botProcs) {
    Write-Host "Stopping Telegram Bot (PID $($p.ProcessId))..."
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# Stop SD Forge
$forgeProcs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object { $_.CommandLine -like "*stable-diffusion-webui-forge*" -or $_.CommandLine -like "*launch.py*" }
foreach ($p in $forgeProcs) {
    Write-Host "Stopping SD Forge (PID $($p.ProcessId))..."
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# Stop any lingering process on port 7860
$connections = Get-NetTCPConnection -LocalPort 7860 -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 0 }
foreach ($c in $connections) {
    Write-Host "Stopping port 7860 listener (PID $($c.OwningProcess))..."
    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
}

Write-Host "All bot and AI services successfully stopped."
