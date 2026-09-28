import os
import sys
import time
import socket
import subprocess
import threading
import webbrowser
import psutil
import json
import urllib.request
import urllib.parse
from PIL import Image, ImageDraw
import pystray

APP_DIR = r"D:\AI"
FORGE_DIR = r"D:\AI\stable-diffusion-webui-forge"
FORGE_BAT = os.path.join(FORGE_DIR, "webui-headless.bat")
BOT_SCRIPT = os.path.join(APP_DIR, "tg_bot_gen.py")
PYTHONW_PATH = r"C:\Users\serqay\AppData\Local\Programs\Python\Python313\pythonw.exe"
if not os.path.exists(PYTHONW_PATH):
    PYTHONW_PATH = sys.executable.replace("python.exe", "pythonw.exe")

ICON_PATH = os.path.join(APP_DIR, "bot_tray_icon.png")
STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
AUTORUN_LNK = os.path.join(STARTUP_DIR, "AI_Bot_Tray.lnk")

CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

# Глобальное состояние
state = {
    "bot_running": False,
    "bot_pid": None,
    "bot_ram_mb": 0,
    "forge_running": False,
    "forge_pid": None,
    "forge_ram_mb": 0,
    "gpu_temp": 0,
    "gpu_load": 0,
    "gpu_power": 0.0,
    "gpu_vram_mb": 0,
    "last_check": 0,
    "stopping": False
}

lock_socket = None

def acquire_single_instance_lock():
    global lock_socket
    try:
        lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_socket.bind(('127.0.0.1', 49151))
        return True
    except socket.error:
        return False

def get_tray_icon_image():
    if os.path.exists(ICON_PATH):
        try:
            return Image.open(ICON_PATH)
        except Exception:
            pass
    # Если иконки нет, рисуем красивый неоновый бейдж
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(25, 20, 45, 255), outline=(0, 230, 255, 255), width=3)
    cx, cy = 32, 32
    points = [
        (cx, cy - 18), (cx + 5, cy - 6), (cx + 18, cy), (cx + 5, cy + 6),
        (cx, cy + 18), (cx - 5, cy + 6), (cx - 18, cy), (cx - 5, cy - 6)
    ]
    d.polygon(points, fill=(0, 255, 200, 255))
    d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(255, 255, 255, 255))
    d.ellipse((44, 44, 60, 60), fill=(0, 230, 100, 255), outline=(20, 20, 20, 255), width=2)
    return img

def is_port_listening(port=7860):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def get_process_stats():
    bot_found = False
    bot_pid = None
    bot_mem = 0

    forge_found = False
    forge_pid = None
    forge_mem = 0

    # 1. Поиск бота
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = " ".join(proc.info.get('cmdline') or [])
            if "tg_bot_gen.py" in cmd:
                bot_found = True
                bot_pid = proc.info['pid']
                bot_mem = round(proc.memory_info().rss / (1024 * 1024), 1)
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 2. Поиск Forge
    port_active = is_port_listening(7860)
    if port_active:
        forge_found = True
        try:
            for conn in psutil.net_connections(kind='tcp'):
                if conn.laddr and conn.laddr.port == 7860 and conn.pid:
                    forge_pid = conn.pid
                    p = psutil.Process(conn.pid)
                    forge_mem = round(p.memory_info().rss / (1024 * 1024), 1)
                    break
        except Exception:
            pass
    else:
        # Проверяем, может он еще инициализируется
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmd = " ".join(proc.info.get('cmdline') or [])
                if "stable-diffusion-webui-forge" in cmd and "launch.py" in cmd:
                    forge_found = True
                    forge_pid = proc.info['pid']
                    forge_mem = round(proc.memory_info().rss / (1024 * 1024), 1)
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    # 3. GPU метрики через nvidia-smi
    temp, load, pwr, vram = 0, 0, 0.0, 0
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        ).strip()
        parts = [p.strip() for p in out.split(",")]
        temp = int(parts[0])
        load = int(parts[1])
        pwr = float(parts[2])
        vram = int(parts[3])
    except Exception:
        pass

    return {
        "bot_running": bot_found,
        "bot_pid": bot_pid,
        "bot_ram_mb": bot_mem,
        "forge_running": forge_found,
        "forge_pid": forge_pid,
        "forge_ram_mb": forge_mem,
        "gpu_temp": temp,
        "gpu_load": load,
        "gpu_power": pwr,
        "gpu_vram_mb": vram
    }

def start_forge_headless():
    if is_port_listening(7860):
        return
    try:
        subprocess.Popen(
            [FORGE_BAT],
            cwd=FORGE_DIR,
            creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS,
            shell=False
        )
    except Exception as e:
        print(f"Error starting Forge: {e}", flush=True)

def start_bot_headless():
    cur = get_process_stats()
    if cur["bot_running"]:
        return
    try:
        subprocess.Popen(
            [PYTHONW_PATH, BOT_SCRIPT],
            cwd=APP_DIR,
            creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
        )
    except Exception as e:
        print(f"Error starting Bot: {e}", flush=True)

def restart_bot(icon=None, item=None):
    flag_path = os.path.join(APP_DIR, "reload_bot.flag")
    cur = get_process_stats()
    if cur["bot_running"]:
        try:
            with open(flag_path, "w", encoding="utf-8") as f:
                f.write("reload")
            if icon:
                try:
                    icon.notify("Запланирован безопасный перезапуск бота (ожидание завершения генераций)...", "AI Bot Service")
                except Exception:
                    pass
            return
        except Exception:
            pass

    # Если бот не был запущен или возникла ошибка записи флага
    start_bot_headless()
    if icon:
        try:
            icon.notify("Telegram бот запущен", "AI Bot Service")
        except Exception:
            pass

def send_tg_shutdown_notification(reason="Закрытие через системный трей"):
    try:
        config_path = os.path.join(APP_DIR, "tg_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            token = cfg.get("bot_token")
            chat_id = cfg.get("chat_id")
            if token and chat_id:
                now_str = time.strftime("%d.%m.%Y %H:%M:%S")
                text = (
                    f"🔴 <b>Бот выключен.</b>\n\n"
                    f"🕒 <b>Время выключения:</b> {now_str}\n"
                    f"ℹ️ <b>Причина:</b> {reason}"
                )
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
                req = urllib.request.Request(url, data=data)
                with urllib.request.urlopen(req, timeout=5):
                    pass
    except Exception:
        pass

def stop_all(icon=None, item=None):
    state["stopping"] = True
    send_tg_shutdown_notification("Выключение сервисов через системный трей (Закрыть всё)")
    if icon:
        try:
            icon.notify("Остановка сервисов и освобождение памяти...", "AI Bot Service")
        except Exception:
            pass

    # 1. Завершить бота
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = " ".join(proc.info.get('cmdline') or [])
            if "tg_bot_gen.py" in cmd:
                proc.kill()
        except Exception:
            pass

    # 2. Завершить Forge
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = " ".join(proc.info.get('cmdline') or [])
            if "stable-diffusion-webui-forge" in cmd or "webui-headless.bat" in cmd:
                proc.kill()
        except Exception:
            pass

    # 3. Закрыть слушателя порта 7860
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr and conn.laddr.port == 7860 and conn.pid:
                try:
                    psutil.Process(conn.pid).kill()
                except Exception:
                    pass
    except Exception:
        pass

    if icon:
        icon.stop()
    sys.exit(0)

def is_autostart_active(item=None):
    return os.path.exists(AUTORUN_LNK)

def toggle_autostart(icon, item):
    if is_autostart_active():
        try:
            if os.path.exists(AUTORUN_LNK):
                os.remove(AUTORUN_LNK)
            icon.notify("Автозапуск отключен", "AI Bot Service")
        except Exception:
            pass
    else:
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortcut(AUTORUN_LNK)
            sc.TargetPath = PYTHONW_PATH
            sc.Arguments = f'"{os.path.join(APP_DIR, "tray_app.py")}"'
            sc.WorkingDirectory = APP_DIR
            sc.IconLocation = os.path.join(APP_DIR, "bot_tray_icon.ico") + ",0"
            sc.Description = "AI Bot Tray Service"
            sc.Save()
            icon.notify("Автозапуск включен (при входе в Windows)", "AI Bot Service")
        except Exception as e:
            icon.notify(f"Ошибка создания ярлыка: {e}", "AI Bot Service")

def show_detailed_status(icon, item):
    st = state
    b_st = f"Онлайн ({st['bot_ram_mb']} МБ)" if st['bot_running'] else "Остановлен"
    f_st = f"Готов на порту 7860 ({st['forge_ram_mb']} МБ)" if st['forge_running'] else "Не отвечает"
    gpu_st = f"{st['gpu_temp']}°C | Загрузка: {st['gpu_load']}% | Мощность: {st['gpu_power']} Вт"
    
    msg = f"• Telegram Бот: {b_st}\n• SD Forge API: {f_st}\n• GPU: {gpu_st}\n• VRAM: {st['gpu_vram_mb']} МБ"
    icon.notify(msg, "Статус AI Bot Service")

def open_folder(icon, item):
    os.startfile(APP_DIR)

def open_webui(icon, item):
    webbrowser.open("http://127.0.0.1:7860/docs")

# Динамические текстовые генераторы для контекстного меню
def menu_bot_status(item):
    if state["bot_running"]:
        return f"🤖 Бот: Онлайн ({state['bot_ram_mb']} МБ)"
    return "🤖 Бот: Остановлен"

def menu_forge_status(item):
    if state["forge_running"]:
        return f"⚡ SD Forge: Готов (порт 7860, {state['forge_ram_mb']} МБ)"
    return "⚡ SD Forge: Запуск / Ожидание..."

def menu_gpu_status(item):
    return f"🌡 GPU: {state['gpu_temp']}°C | Нагрузка: {state['gpu_load']}% | {state['gpu_power']} Вт"

def monitor_loop(icon):
    while not state["stopping"]:
        try:
            stats = get_process_stats()
            state.update(stats)

            # Авто-поднятие бота, если он упал
            if not state["bot_running"] and not state["stopping"]:
                start_bot_headless()

            # Обновление подсказки при наведении
            b_txt = "Онлайн" if state["bot_running"] else "Оффлайн"
            f_txt = "Готов" if state["forge_running"] else "Ожидание"
            tooltip = f"AI Bot: {b_txt} | Forge: {f_txt} | GPU: {state['gpu_temp']}°C ({state['gpu_load']}%)"
            icon.title = tooltip[:127]
        except Exception:
            pass
        time.sleep(4)

def main():
    if not acquire_single_instance_lock():
        sys.exit(0)

    # Запуск фоновых сервисов
    start_forge_headless()
    start_bot_headless()

    img = get_tray_icon_image()

    menu = pystray.Menu(
        pystray.MenuItem(menu_bot_status, None, enabled=False),
        pystray.MenuItem(menu_forge_status, None, enabled=False),
        pystray.MenuItem(menu_gpu_status, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("📋 Показать подробный статус", show_detailed_status),
        pystray.MenuItem("📁 Открыть папку D:\\AI", open_folder),
        pystray.MenuItem("🔄 Перезапустить Telegram бота", restart_bot),
        pystray.MenuItem("☑ Автозапуск с Windows", toggle_autostart, checked=is_autostart_active),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Закрыть всё и выгрузить из памяти", stop_all)
    )

    icon = pystray.Icon("AIBotTray", img, "AI Bot Service: Загрузка...", menu=menu)

    # Поток мониторинга состояния
    t = threading.Thread(target=monitor_loop, args=(icon,), daemon=True)
    t.start()

    icon.run()

if __name__ == "__main__":
    main()
