import threading
import urllib.request
import json
import time
from bot.telegram_api import edit_message
from bot.config import API_URL

def progress_bar_worker(token, chat_id, message_id, stop_event, prefix_text):
    base_url = API_URL.replace("/txt2img", "/progress?skip_current_image=true")
    last_progress = -1
    while not stop_event.is_set():
        time.sleep(1.5)
        if stop_event.is_set():
            break
        try:
            req = urllib.request.Request(base_url)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                progress = data.get('progress', 0.0)
                if progress > 0 and abs(progress - last_progress) > 0.1:
                    last_progress = progress
                    pct = int(progress * 100)
                    filled = int(progress * 10)
                    bar = "█" * filled + "░" * (10 - filled)
                    text = f"{prefix_text}\n\n⏳ Прогресс: [{bar}] {pct}%"
                    edit_message(token, chat_id, message_id, text, parse_mode="HTML")
        except Exception:
            pass
