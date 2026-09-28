import os
import sys
import time
import json
import urllib.request
import threading

import atexit
import signal
from datetime import datetime

import bot.config as config
from bot.config import (
    load_config, RESTART_NOTIFY_PATH, get_session
)
from bot.database import touch_user
from bot.telegram_api import send_message
from bot.menus import make_main_menu
from bot.worker import queue_worker, reload_flag_watcher, memory_guardian_loop
from bot.handlers import (
    handle_pre_checkout_query,
    handle_callback_query,
    handle_message
)

_shutdown_notified = False
_shutdown_lock = threading.Lock()

def notify_bot_shutdown(reason="Завершение работы процесса"):
    global _shutdown_notified
    with _shutdown_lock:
        if _shutdown_notified or config.is_restarting or config.is_shutting_down:
            return
        _shutdown_notified = True

    try:
        cfg = load_config()
        token = cfg.get("bot_token", "").strip()
        admin_chat_id = str(cfg.get("chat_id", "")).strip()
        if token and admin_chat_id:
            now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            msg = (
                f"🔴 <b>Бот выключен.</b>\n\n"
                f"🕒 <b>Время выключения:</b> {now_str}\n"
                f"ℹ️ <b>Причина:</b> {reason}"
            )
            send_message(token, admin_chat_id, msg)
    except Exception as e:
        print(f"Error sending shutdown notification: {e}", flush=True)

atexit.register(notify_bot_shutdown, "Штатное завершение работы (atexit)")

def _signal_handler(signum, frame):
    sig_names = {
        signal.SIGINT: "Остановка процесса SIGINT (Ctrl+C)",
        signal.SIGTERM: "Остановка процесса SIGTERM",
    }
    if hasattr(signal, "SIGBREAK"):
        sig_names[signal.SIGBREAK] = "Остановка процесса SIGBREAK (Ctrl+Break)"
    reason = sig_names.get(signum, f"Сигнал ОС ({signum})")
    notify_bot_shutdown(reason)
    sys.exit(0)

try:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)
except Exception:
    pass

if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes

        HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        def _console_ctrl_handler(ctrl_type):
            ctrl_reasons = {
                0: "Ctrl+C в консоли",
                1: "Ctrl+Break в консоли",
                2: "Закрытие окна консоли",
                5: "Выход пользователя из Windows (Logoff)",
                6: "Выключение компьютера (Windows Shutdown)"
            }
            reason = ctrl_reasons.get(ctrl_type, f"Событие консоли Windows ({ctrl_type})")
            notify_bot_shutdown(reason)
            return False

        _global_ctrl_handler = HandlerRoutine(_console_ctrl_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_global_ctrl_handler, True)
    except Exception:
        pass

def main():
    print("=== GummyFlux Telegram Bot Modular System Starting ===", flush=True)
    cfg = load_config()
    token = cfg.get("bot_token", "").strip()
    admin_chat_id = str(cfg.get("chat_id", "")).strip()

    if not token:
        print("Ошибка: отсутствует токен бота в конфиге.", flush=True)
        return

    # Запуск фонового воркера очереди генераций
    threading.Thread(target=queue_worker, args=(token,), daemon=True).start()

    # Запуск фонового стража оперативной памяти (сброс RAM Forge/PyTorch)
    threading.Thread(target=memory_guardian_loop, daemon=True).start()

    admin_uname = cfg.get("admin_username", "admin").strip().lstrip("@")
    if admin_chat_id:
        touch_user(admin_chat_id, admin_uname, "Администратор")

    # Проверка уведомления о завершении безопасного перезапуска (только администратору)
    is_restart = os.path.exists(RESTART_NOTIFY_PATH)
    if is_restart:
        try:
            with open(RESTART_NOTIFY_PATH, "r", encoding="utf-8") as f:
                r_info = json.load(f)
            os.remove(RESTART_NOTIFY_PATH)
            r_start = r_info.get("start_time", time.time())
            r_elapsed = round(time.time() - r_start, 1)
            target_admin = r_info.get("chat_id") or admin_chat_id
            if target_admin:
                now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                send_message(
                    token, target_admin,
                    f"✅ <b>Бот успешно перезагружен и обновлен!</b>\n\n"
                    f"🕒 <b>Время:</b> {now_str}\n"
                    f"⏱ <b>Время перезапуска:</b> {r_elapsed} сек.\n"
                    f"✨ Категории настроек, четкие промты ИИ и распознавание по фото активны."
                )
        except Exception as e:
            print(f"Error handling restart notify: {e}", flush=True)
    else:
        if admin_chat_id:
            now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            startup_msg = (
                f"🟢 <b>Бот включен и готов к работе!</b>\n\n"
                f"🕒 <b>Время запуска:</b> {now_str}\n"
                f"🚀 Очередь задач, фоновые службы и меню успешно запущены."
            )
            send_message(token, admin_chat_id, startup_msg)

    if admin_chat_id:
        sess = get_session(admin_chat_id)
        menu_text, menu_markup = make_main_menu(sess, user_id=admin_chat_id, username=admin_uname)
        send_message(token, admin_chat_id, menu_text, reply_markup=menu_markup)

    # Запуск фонового вотчера безопасного обновления / остановки
    threading.Thread(target=reload_flag_watcher, args=(token, admin_chat_id), daemon=True).start()

    last_update_id = 0
    try:
        init_url = f"https://api.telegram.org/bot{token}/getUpdates?offset=-1"
        with urllib.request.urlopen(init_url, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
            if d.get("ok") and d.get("result"):
                last_update_id = d["result"][-1]["update_id"]
    except Exception:
        pass

    stored_searches = {}

    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tg_worker")

    def process_update(upd):
        try:
            if "pre_checkout_query" in upd:
                handle_pre_checkout_query(token, upd)
            elif "callback_query" in upd:
                handle_callback_query(token, upd, stored_searches)
            elif "message" in upd:
                handle_message(token, upd["message"], stored_searches)
        except Exception as err:
            print(f"Error processing update: {err}", flush=True)

    while True:
        try:
            poll_url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=25"
            with urllib.request.urlopen(poll_url, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
                if data.get("ok") and data.get("result"):
                    for upd in data["result"]:
                        last_update_id = upd["update_id"]
                        executor.submit(process_update, upd)

        except Exception as e:
            # Сетевые таймауты и временные ошибки Telegram API
            time.sleep(1)

if __name__ == "__main__":
    main()
