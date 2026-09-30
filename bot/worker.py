import os
import sys
import time
import json
import uuid
import subprocess
import threading
import html
from datetime import datetime
import bot.config as config
from bot.config import (
    APP_DIR, HISTORY_DIR, RELOAD_FLAG_PATH, STOP_FLAG_PATH, RESTART_NOTIFY_PATH,
    active_lock, active_generations, generation_queue,
    gpu_lock, is_restarting_lock,
    is_shutting_down_lock, MAX_HISTORY_IMAGES,
    get_admin_chat_id, AVAILABLE_MODELS, DEFAULT_MODEL, DEFAULT_CFG_SCALE
)
from bot.sd_client import generate_image, is_generation_busy, trim_system_memory, is_backend_online
from bot.database import log_generation, refund_user_generation, is_admin, get_pc_notifies, clear_pc_notifies
from bot.telegram_api import send_message, send_photo

def cleanup_old_history_images(history_dir, max_files=MAX_HISTORY_IMAGES):
    try:
        files = [
            os.path.join(history_dir, f)
            for f in os.listdir(history_dir)
            if f.startswith("gen_") and f.endswith(".png")
        ]
        if len(files) > max_files:
            files.sort(key=os.path.getmtime)
            to_remove = files[:len(files) - max_files]
            for fpath in to_remove:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    except Exception as e:
        print(f"Error cleaning history images: {e}", flush=True)

def perform_safe_reload(token, notify_chat_id=None):
    admin_id = get_admin_chat_id()
    with is_restarting_lock:
        if config.is_restarting:
            target_to_notify = str(notify_chat_id) if notify_chat_id else admin_id
            if target_to_notify:
                send_message(token, target_to_notify, "Перезапуск уже запланирован и выполняется.")
            return
        config.is_restarting = True

    def _worker():
        try:
            admin_target = admin_id or (str(notify_chat_id) if notify_chat_id else "")
            with active_lock:
                a_count = len(active_generations)
            q_count = generation_queue.qsize()
            if admin_target and (a_count > 0 or q_count > 0 or gpu_lock.locked()):
                send_message(token, admin_target, f"⏳ Запущен процесс безопасного обновления.\nАктивных задач: {a_count}, в очереди: {q_count}.\nОжидаем завершения генераций перед перезапуском...")

            wait_start = time.time()
            while is_generation_busy():
                if time.time() - wait_start > 120:
                    break
                time.sleep(0.5)

            if admin_target:
                send_message(token, admin_target, "🚀 Генерации завершены. Перезапуск бота (~1-2 сек)...")

            try:
                with open(RESTART_NOTIFY_PATH, "w", encoding="utf-8") as f:
                    json.dump({"chat_id": admin_target, "start_time": time.time()}, f)
            except Exception:
                pass

            python_exe = sys.executable
            candidate_pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if os.path.exists(candidate_pyw):
                python_exe = candidate_pyw
            elif sys.platform == "win32":
                import shutil
                pyw = shutil.which("pythonw")
                if pyw and os.path.exists(pyw):
                    python_exe = pyw

            main_script = os.path.join(APP_DIR, "tg_bot_gen.py")
            subprocess.Popen(
                [python_exe, main_script],
                cwd=APP_DIR,
                creationflags=0x08000000 | 0x00004000
            )
            time.sleep(0.3)
            os._exit(0)
        except Exception as e:
            print(f"Safe reload error: {e}", flush=True)

    threading.Thread(target=_worker, daemon=True).start()

def perform_safe_shutdown(token, notify_chat_id=None, reason="Команда администратора"):
    admin_id = get_admin_chat_id()
    target_to_notify = str(notify_chat_id) if notify_chat_id else admin_id
    with is_shutting_down_lock:
        if config.is_shutting_down:
            if target_to_notify:
                send_message(token, target_to_notify, "Выключение бота уже выполняется.")
            return
        config.is_shutting_down = True

    def _worker():
        try:
            with active_lock:
                a_count = len(active_generations)
            q_count = generation_queue.qsize()
            if target_to_notify and (a_count > 0 or q_count > 0 or gpu_lock.locked()):
                send_message(token, target_to_notify, f"⏳ Запущен процесс выключения бота.\nАктивных задач: {a_count}, в очереди: {q_count}.\nОжидаем завершения генераций перед выключением...")

            wait_start = time.time()
            while is_generation_busy():
                if time.time() - wait_start > 60:
                    break
                time.sleep(0.5)

            now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            if target_to_notify:
                send_message(
                    token, target_to_notify,
                    f"🔴 <b>Бот выключен.</b>\n\n"
                    f"🕒 <b>Время выключения:</b> {now_str}\n"
                    f"ℹ️ <b>Причина:</b> {reason}\n"
                    f"💤 Все процессы и службы генерации остановлены."
                )
            time.sleep(1)
            os._exit(0)
        except Exception as e:
            print(f"Safe shutdown error: {e}", flush=True)
            os._exit(0)

    threading.Thread(target=_worker, daemon=True).start()

def reload_flag_watcher(token, admin_chat_id):
    while True:
        try:
            if os.path.exists(STOP_FLAG_PATH):
                try:
                    os.remove(STOP_FLAG_PATH)
                except Exception:
                    pass
                perform_safe_shutdown(token, admin_chat_id, reason="Получен системный флаг остановки stop_bot.flag")
                break
            if os.path.exists(RELOAD_FLAG_PATH):
                try:
                    os.remove(RELOAD_FLAG_PATH)
                except Exception:
                    pass
                perform_safe_reload(token, admin_chat_id)
                break
        except Exception:
            pass
        time.sleep(1)

def queue_worker(token):
    while True:
        task_item = generation_queue.get()
        if task_item is None:
            break
            
        if isinstance(task_item, tuple) and len(task_item) == 3:
            _, _, task = task_item
        else:
            task = task_item
        consumed_type = None
        user_id = None
        chat_id = None
        try:
            steps = 20
            is_custom = False
            if isinstance(task, dict):
                chat_id = task["chat_id"]
                user_id = str(task["user_id"])
                username = task.get("username", "")
                first_name = task.get("first_name", "")
                prompt = task["prompt"]
                is_nsfw = task.get("is_nsfw", True)
                width = task.get("width", 832)
                height = task.get("height", 1216)
                char_name = task.get("char_name", "Персонаж")
                pose_name = task.get("pose_name", "Поза")
                env_name = task.get("env_name", "Окружение")
                is_custom = task.get("is_custom", False)
                steps = task.get("steps", 20)
                consumed_type = task.get("consumed_type")
                with_partner = task.get("with_partner", False)
                model = task.get("model", DEFAULT_MODEL)
                char_gender = task.get("char_gender", "female")
                cfg_scale = task.get("cfg_scale", DEFAULT_CFG_SCALE)
            elif len(task) >= 14:
                _tok, chat_id, user_id, username, first_name, prompt, is_nsfw, width, height, char_name, pose_name, env_name, is_custom, steps = task[:14]
                with_partner = False
                model = DEFAULT_MODEL
                char_gender = "female"
                cfg_scale = DEFAULT_CFG_SCALE
            elif len(task) == 13:
                _tok, chat_id, user_id, username, first_name, prompt, is_nsfw, width, height, char_name, pose_name, env_name, is_custom = task
                with_partner = False
                model = DEFAULT_MODEL
                char_gender = "female"
                cfg_scale = DEFAULT_CFG_SCALE
            elif len(task) == 12:
                chat_id, user_id, username, first_name, prompt, is_nsfw, width, height, char_name, pose_name, env_name, is_custom = task
                with_partner = False
                model = DEFAULT_MODEL
                char_gender = "female"
                cfg_scale = DEFAULT_CFG_SCALE
            else:
                continue

            user_id = str(user_id)
            steps = int(steps)
            if not is_admin(user_id, username):
                steps = max(15, min(30, steps))
            else:
                steps = max(5, min(60, steps))

            try:
                cfg_scale = round(min(max(1.0, float(cfg_scale)), 15.0), 1)
            except Exception:
                cfg_scale = DEFAULT_CFG_SCALE

            model_info = AVAILABLE_MODELS.get(model, AVAILABLE_MODELS.get(DEFAULT_MODEL, {}))
            model_badge = model_info.get("name", "NoobAI XL")

            msg_res = send_message(token, chat_id, f"Ваша очередь подошла! Рендеринг: {html.escape(char_name)} ({model_badge}, {width}x{height}, {steps} samples, CFG {cfg_scale})... (ожидайте ~5-8 сек)")
            progress_event = threading.Event()
            if msg_res and msg_res.get("ok"):
                msg_id = msg_res.get("result", {}).get("message_id")
                from bot.progress import progress_bar_worker
                prefix = f"Ваша очередь подошла! Рендеринг: {html.escape(char_name)} ({model_badge}, {width}x{height})"
                threading.Thread(target=progress_bar_worker, args=(token, chat_id, msg_id, progress_event, prefix), daemon=True).start()
            
            with gpu_lock:
                if c_sess.get("use_img2img") and c_sess.get("init_image_b64"):
                    from bot.img2img import generate_img2img
                    b64 = c_sess.get("init_image_b64").split(",")[-1]
                    img_bytes, elapsed = generate_img2img(
                        prompt, b64, is_nsfw=is_nsfw, width=width, height=height,
                        is_custom=is_custom, steps=steps, model=model, char_gender=char_gender, cfg_scale=cfg_scale
                    )
                    c_sess["use_img2img"] = False
                    from bot.config import save_sessions
                    save_sessions()
                else:
                    img_bytes, elapsed = generate_image(
                        prompt, is_nsfw=is_nsfw, width=width, height=height,
                        is_custom=is_custom, steps=steps, with_partner=with_partner,
                        model=model, char_gender=char_gender, cfg_scale=cfg_scale
                    )
            progress_event.set()

            if img_bytes:
                img_id = uuid.uuid4().hex[:8]
                img_filename = f"gen_{int(time.time())}_{img_id}.png"
                img_path = os.path.join(HISTORY_DIR, img_filename)
                try:
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    cleanup_old_history_images(HISTORY_DIR)
                except Exception as e:
                    print(f"Error saving history image: {e}", flush=True)
                    img_path = ""

                log_generation(
                    user_id, username, first_name,
                    "nsfw" if is_nsfw else "sfw",
                    char_name, pose_name, env_name,
                    f"{width}x{height}", prompt, elapsed,
                    is_custom=is_custom, image_path=img_path, img_id=img_id
                )
                if is_custom:
                    caption = f"🎨 Кастомный арт готов за {elapsed} сек. [{model_badge} | {width}x{height} | {steps} steps | CFG {cfg_scale}]"
                    reply_markup = {
                        "inline_keyboard": [
                            [{"text": "🔄 Еще вариант", "callback_data": "quick_rerun"},
                             {"text": "🏠 Главное меню", "callback_data": "menu_main"}]
                        ]
                    }
                else:
                    p_low = prompt.lower()
                    is_male_char = (char_gender == "male") or (any(k in p_low for k in ["1boy", "1man", " male", "homdan"]) and not any(k in p_low for k in ["1girl", "female", "woman"]))
                    done_word = "готов" if is_male_char else "готова"
                    caption = f"✨ <b>{html.escape(char_name)}</b> {done_word} за {elapsed} сек. [{model_badge} | {width}x{height} | {steps} steps | CFG {cfg_scale}]"
                    toggle_btn = "👗 Одеть (SFW)" if is_nsfw else "🔥 Раздеть (NSFW)"
                    reply_markup = {
                        "inline_keyboard": [
                            [{"text": "🔄 Еще вариант", "callback_data": "quick_rerun"},
                             {"text": "💃 Сменить позу", "callback_data": "menu_pose"}],
                            [{"text": toggle_btn, "callback_data": "quick_toggle_mode"},
                             {"text": "🏠 Главное меню", "callback_data": "menu_main"}]
                        ]
                    }
                delivered = send_photo(
                    token, chat_id, img_bytes,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                if not delivered:
                    # Изображение уже сохранено в img_path: не теряем результат.
                    send_message(
                        token,
                        chat_id,
                        "⚠️ Рисунок создан, но Telegram не принял файл. "
                        "Генерация сохранена на сервере. Обратитесь к администратору."
                    )
                    print(
                        f"DELIVERY FAILED: user={user_id}, image={img_path}, id={img_id}",
                        flush=True,
                    )
            else:
                refund_user_generation(user_id, consumed_type)
                send_message(
                    token, chat_id,
                    "❌ <b>Ошибка генерации через нейросеть.</b>\n\n"
                    "Служба рендеринга WebUI временно недоступна или произошел сбой видеопамяти.\n"
                    "✨ Ваша попытка генерации не сгорела и возвращена на баланс!"
                )
        except Exception as e:
            print(f"Queue worker exception: {e}", flush=True)
            try:
                if user_id:
                    refund_user_generation(user_id, consumed_type)
                if chat_id:
                    send_message(
                        token, chat_id,
                        "❌ Произошла непредвиденная ошибка при создании арта. Попытка возвращена на баланс."
                    )
            except Exception:
                pass
        finally:
            try:
                if user_id:
                    with active_lock:
                        active_generations.discard(str(user_id))
            except Exception:
                pass
            generation_queue.task_done()
            trim_system_memory()

def memory_guardian_loop():
    """
    Фоновый страж памяти: каждые 30 секунд очищает Working Set процессов Python и SD Forge,
    предотвращая удержание 15+ ГБ оперативной памяти в простое.
    """
    while True:
        try:
            trim_system_memory()
        except Exception:
            pass
        time.sleep(30)

def pc_monitor_worker(token):
    """
    Фоновый мониторинг доступности локального сервера генерации (SD Forge).
    Когда сервер переходит из состояния 'offline' в 'online', рассылает уведомления
    всем пользователям, ожидавшим включения ПК, и очищает список ожидания.
    """
    was_online = is_backend_online()
    while True:
        try:
            time.sleep(10)
            is_now_online = is_backend_online()
            if not was_online and is_now_online:
                waiters = get_pc_notifies()
                if waiters:
                    clear_pc_notifies()
                    notify_msg = (
                        "⚡ <b>Компьютер включен! Генерация снова доступна.</b>\n\n"
                        "Служба нейросети активна и готова к созданию артов. Нажмите кнопку ниже для старта:"
                    )
                    reply_markup = {
                        "inline_keyboard": [
                            [{"text": "🎨 Создать арт", "callback_data": "menu_main"}]
                        ]
                    }
                    for cid in waiters:
                        try:
                            send_message(token, cid, notify_msg, reply_markup=reply_markup)
                            time.sleep(0.05)
                        except Exception as e:
                            print(f"Error sending PC online notify to {cid}: {e}", flush=True)
            was_online = is_now_online
        except Exception as e:
            print(f"PC monitor worker error: {e}", flush=True)
