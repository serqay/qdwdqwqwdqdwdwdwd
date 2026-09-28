import os
import time
import json
import html
import random
import threading
from bot.config import (
    active_lock, active_generations, generation_queue,
    STARS_PACKAGES, DEFAULT_CHARS, DEFAULT_CHARS_FEMALE, DEFAULT_CHARS_MALE,
    DEFAULT_POSES, DEFAULT_POSES_SFW, DEFAULT_POSES_NSFW, DEFAULT_ENVS,
    get_session, save_sessions, BOT_USERNAME,
    AVAILABLE_MODELS, DEFAULT_MODEL, DEFAULT_CFG_SCALE
)
from bot.database import (
    load_db, touch_user, is_admin, get_user_limits_status,
    consume_user_generation, refund_user_generation, add_bonus_credits, set_user_base_limit,
    add_user_bonus_generations, reset_user_daily_count,
    reset_all_users_daily_limits_async, find_user_by_query,
    log_message, process_referral
)
from bot.telegram_api import (
    api_call, send_message, edit_message, send_photo,
    get_file, download_file
)
from bot.menus import (
    make_main_menu, make_char_menu, make_pose_menu, make_env_menu,
    make_settings_menu, make_samples_menu, make_models_menu, make_resolution_menu, make_cfg_menu, render_buy_stars_menu,
    make_admin_menu, render_admin_stats, render_admin_users,
    render_admin_user_card, render_admin_edit_base_menu,
    render_admin_grant_menu, render_admin_history, render_admin_messages,
    make_confirm_generation_menu, make_confirm_custom_menu, make_referral_menu
)
from bot.search import (
    search_online_characters, search_online_poses, search_online_environment
)
from bot.ai_character import (
    describe_character_by_name, describe_character_by_photo,
    enhance_prompt_with_ai
)
from bot.worker import perform_safe_reload, perform_safe_shutdown

def reply_or_edit(token, chat_id, msg, text, reply_markup=None):
    if not msg:
        return send_message(token, chat_id, text, reply_markup=reply_markup)
    if msg.get("photo") or msg.get("document") or msg.get("video") or msg.get("animation"):
        return send_message(token, chat_id, text, reply_markup=reply_markup)
    msg_id = msg.get("message_id")
    if not msg_id:
        return send_message(token, chat_id, text, reply_markup=reply_markup)
    res = edit_message(token, chat_id, msg_id, text, reply_markup=reply_markup)
    if not res or not res.get("ok"):
        desc = (res.get("description") if res else "") or ""
        if "message is not modified" in desc:
            return res
        return send_message(token, chat_id, text, reply_markup=reply_markup)
    return res

def handle_pre_checkout_query(token, upd):
    pcq = upd["pre_checkout_query"]
    pcq_id = pcq["id"]
    api_call(token, "answerPreCheckoutQuery", {"pre_checkout_query_id": pcq_id, "ok": True})

def handle_callback_query(token, upd, stored_searches):
    cb = upd["callback_query"]
    cb_id = cb["id"]
    c_chat_id = str(cb["message"]["chat"]["id"])
    msg_id = cb["message"]["message_id"]
    c_data = cb.get("data", "")
    cb_user = cb.get("from", {})
    u_id = str(cb_user.get("id", c_chat_id))
    u_name = cb_user.get("username", "")
    u_fname = cb_user.get("first_name", "")

    touch_user(u_id, u_name, u_fname)
    c_sess = get_session(c_chat_id)
    api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id})

    # Проверка прав администратора
    if c_data.startswith("admin_"):
        if not is_admin(u_id, u_name):
            send_message(token, c_chat_id, "Доступ к панели администратора разрешен только администратору.")
            return

    # 1. ГЛАВНОЕ МЕНЮ И КАТЕГОРИИ
    if c_data == "menu_main":
        c_sess["state"] = "idle"
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_char":
        c_sess["state"] = "idle"
        t, m = make_char_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_pose":
        c_sess["state"] = "idle"
        t, m = make_pose_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_env":
        c_sess["state"] = "idle"
        t, m = make_env_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_settings":
        c_sess["state"] = "idle"
        t, m = make_settings_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    # 2. ПРЕСЕТЫ И СЛУЧАЙНЫЙ ВЫБОР
    elif c_data == "main_toggle_mode":
        c_sess["mode"] = "sfw" if c_sess.get("mode") == "nsfw" else "nsfw"
        save_sessions()
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data in ["action_toggle_char_gender", "settings_toggle_char_gender"]:
        cur_g = c_sess.get("char_gender", "female")
        new_g = "male" if cur_g == "female" else "female"
        c_sess["char_gender"] = new_g
        if new_g == "male":
            if any(c[0] == c_sess.get("char_name") for c in DEFAULT_CHARS_FEMALE):
                m_char = DEFAULT_CHARS_MALE[0]
                c_sess["char_name"] = m_char[0]
                c_sess["char_prompt"] = m_char[1]
            else:
                p = c_sess.get("char_prompt", "")
                if "1girl" in p:
                    c_sess["char_prompt"] = p.replace("1girl", "1boy")
        else:
            if any(c[0] == c_sess.get("char_name") for c in DEFAULT_CHARS_MALE):
                f_char = DEFAULT_CHARS_FEMALE[0]
                c_sess["char_name"] = f_char[0]
                c_sess["char_prompt"] = f_char[1]
            else:
                p = c_sess.get("char_prompt", "")
                if "1boy" in p:
                    c_sess["char_prompt"] = p.replace("1boy", "1girl")
        save_sessions()
        if c_data == "settings_toggle_char_gender":
            t, m = make_settings_menu(c_sess, user_id=u_id, username=u_name)
        else:
            t, m = make_char_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("preset_char_"):
        parts = c_data.split("_")
        if len(parts) >= 4 and parts[2] in ["fem", "male"]:
            g_type = parts[2]
            idx = int(parts[3])
            char_list = DEFAULT_CHARS_MALE if g_type == "male" else DEFAULT_CHARS_FEMALE
            if 0 <= idx < len(char_list):
                c_sess["char_gender"] = "male" if g_type == "male" else "female"
                c_sess["char_name"] = char_list[idx][0]
                c_sess["char_prompt"] = char_list[idx][1]
        else:
            idx = int(parts[2])
            cur_g = c_sess.get("char_gender", "female")
            char_list = DEFAULT_CHARS_MALE if cur_g == "male" else DEFAULT_CHARS_FEMALE
            if 0 <= idx < len(char_list):
                c_sess["char_name"] = char_list[idx][0]
                c_sess["char_prompt"] = char_list[idx][1]
        save_sessions()
        t, m = make_char_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "char_random":
        cur_g = c_sess.get("char_gender", "female")
        char_list = DEFAULT_CHARS_MALE if cur_g == "male" else DEFAULT_CHARS_FEMALE
        char = random.choice(char_list)
        c_sess["char_name"] = char[0]
        c_sess["char_prompt"] = char[1]
        save_sessions()
        t, m = make_char_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("preset_pose_"):
        idx = int(c_data.replace("preset_pose_", ""))
        if 0 <= idx < len(DEFAULT_POSES):
            pose = DEFAULT_POSES[idx]
            c_sess["pose_name"] = pose[0]
            c_sess["pose_prompt"] = pose[1]
        save_sessions()
        t, m = make_pose_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "pose_random_sfw":
        pose = random.choice(DEFAULT_POSES_SFW)
        c_sess["pose_name"] = pose[0]
        c_sess["pose_prompt"] = pose[1]
        save_sessions()
        t, m = make_pose_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "pose_random_nsfw":
        pose = random.choice(DEFAULT_POSES_NSFW)
        c_sess["pose_name"] = pose[0]
        c_sess["pose_prompt"] = pose[1]
        save_sessions()
        t, m = make_pose_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "pose_random":
        pose = random.choice(DEFAULT_POSES)
        c_sess["pose_name"] = pose[0]
        c_sess["pose_prompt"] = pose[1]
        save_sessions()
        t, m = make_pose_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "env_random":
        env = random.choice(DEFAULT_ENVS)
        c_sess["env_name"] = env[0]
        c_sess["env_prompt"] = env[1]
        save_sessions()
        t, m = make_env_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("preset_env_"):
        idx = int(c_data.replace("preset_env_", ""))
        if 0 <= idx < len(DEFAULT_ENVS):
            env = DEFAULT_ENVS[idx]
            c_sess["env_name"] = env[0]
            c_sess["env_prompt"] = env[1]
        save_sessions()
        t, m = make_env_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    # 3. НАСТРОЙКИ (РЕЖИМ, РАЗРЕШЕНИЕ И SAMPLES)
    elif c_data == "action_toggle_mode":
        c_sess["mode"] = "sfw" if c_sess.get("mode") == "nsfw" else "nsfw"
        save_sessions()
        t, m = make_settings_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "action_toggle_partner":
        c_sess["partner_mode"] = "with_male" if c_sess.get("partner_mode") != "with_male" else "none"
        save_sessions()
        t, m = make_settings_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_resolution":
        t, m = make_resolution_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("res_"):
        parts = c_data.replace("res_", "").split("_")
        w, h = int(parts[0]), int(parts[1])
        c_sess["width"] = w
        c_sess["height"] = h
        c_sess["state"] = "idle"
        save_sessions()
        t, m = make_settings_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_models":
        t, m = make_models_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("set_model_"):
        chosen = c_data.replace("set_model_", "")
        if chosen in AVAILABLE_MODELS:
            c_sess["model"] = chosen
            c_sess["state"] = "idle"
            save_sessions()
        t, m = make_models_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_samples":
        t, m = make_samples_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("set_samples_"):
        val = int(c_data.replace("set_samples_", ""))
        if not is_admin(u_id, u_name):
            val = max(15, min(25, val))
        else:
            val = max(5, min(60, val))
        c_sess["steps"] = val
        save_sessions()
        t, m = make_samples_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "start_custom_samples":
        c_sess["state"] = "awaiting_custom_samples"
        save_sessions()
        if is_admin(u_id, u_name):
            text = (
                "⚡ <b>ВВЕДИТЕ ШАГИ СЕМПЛИРОВАНИЯ (SAMPLES)</b>\n\n"
                "Напишите точное число шагов сообщением в этот чат (от 5 до 60).\n"
                "Рекомендуемые значения: 15–30."
            )
        else:
            text = (
                "⚡ <b>ВВЕДИТЕ ШАГИ СЕМПЛИРОВАНИЯ (SAMPLES)</b>\n\n"
                "Напишите число шагов сообщением в этот чат (от 15 до 25).\n"
                "Рекомендуемое значение: 20."
            )
        markup = {"inline_keyboard": [[{"text": "◀️ Отмена", "callback_data": "menu_samples"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "start_custom_res":
        c_sess["state"] = "awaiting_resolution"
        save_sessions()
        text = (
            "📐 <b>ВВЕДИТЕ РАЗРЕШЕНИЕ В ЧАТ</b>\n\n"
            "Напишите желаемую ширину и высоту в формате ШИРИНАxВЫСОТА (например, 960x1280 или 1080x1080).\n\n"
            "Правила:\n"
            "• Стороны не должны превышать 1500 пикселей\n"
            "• Минимальный размер: 512 пикселей"
        )
        markup = {"inline_keyboard": [[{"text": "◀️ Назад в настройки", "callback_data": "menu_settings"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "menu_cfg":
        t, m = make_cfg_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("set_cfg_"):
        val_str = c_data.replace("set_cfg_", "")
        try:
            val = round(min(max(1.0, float(val_str)), 15.0), 1)
            c_sess["cfg_scale"] = val
            save_sessions()
        except Exception:
            pass
        t, m = make_cfg_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "start_custom_cfg":
        c_sess["state"] = "awaiting_custom_cfg"
        save_sessions()
        text = (
            "🎯 <b>ВВЕДИТЕ ЗНАЧЕНИЕ CFG SCALE (ОТ 1 ДО 15)</b>\n\n"
            "Напишите желаемую силу соблюдения правил промпта числом в этот чат (например: <code>4.5</code>, <code>5.5</code>, <code>7.0</code>, <code>10</code> или <code>15</code>).\n\n"
            "• Допустимый диапазон: от <b>1.0</b> до <b>15.0</b>\n"
            "• Стандартный баланс: <b>5.5</b>"
        )
        markup = {"inline_keyboard": [[{"text": "◀️ Отмена", "callback_data": "menu_cfg"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    # 4. ФУНКЦИИ ИИ
    elif c_data == "start_char_photo":
        c_sess["state"] = "awaiting_char_photo"
        save_sessions()
        text = (
            "📸 <b>ПЕРСОНАЖ ПО ФОТО</b>\n\n"
            "Отправьте фотографию или арт персонажа прямо в этот чат.\n\n"
            "ИИ проанализирует изображение, "
            "определит внешность, прическу, цвет глаз, одежду и сформирует точный набор Danbooru-тегов "
            "для создания арта в нашем стиле."
        )
        kb = [[{"text": "◀️ Отмена / Назад", "callback_data": "menu_char"}]]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "start_ai_describe_char":
        c_sess["state"] = "awaiting_ai_char_name"
        save_sessions()
        cur_name = c_sess.get("char_name", "")
        text = (
            "✨ <b>РАСПОЗНАВАНИЕ ПЕРСОНАЖА ЧЕРЕЗ ИИ</b>\n\n"
            "Если нейросеть не знает вашего персонажа или рисует его неточно, "
            "ИИ найдет детали внешности персонажа и переведет их в точные Danbooru-теги!\n\n"
            "Отправьте имя персонажа на английском сообщением в чат "
            "(например: <i>Jane Doe (Zenless Zone Zero), Makima, Yor Briar, 2B, Ahri, Loona</i>):"
        )
        kb = []
        if cur_name and cur_name != "Не выбран":
            kb.append([{"text": f"✨ Описать текущего: '{cur_name[:30]}'", "callback_data": "ai_describe_current"}])
        kb.append([{"text": "◀️ Отмена / Назад", "callback_data": "menu_char"}])
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "ai_describe_current":
        char_n = c_sess.get("char_name", "anime girl")
        reply_or_edit(token, c_chat_id, cb.get("message"), f"🔍 <i>Анализирую внешность '{html.escape(char_n)}' через ИИ... Пожалуйста, подождите (~5 сек)...</i>")

        def _bg_describe():
            tags = describe_character_by_name(char_n)
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"✅ <b>Внешность '{html.escape(char_n)}' успешно сформирована ИИ!</b>\n\n"
                f"<b>Danbooru-теги персонажа:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"Нажмите кнопку ниже, чтобы сгенерировать арт:"
            )
            t_main, m_main = make_main_menu(c_sess, user_id=u_id, username=u_name)
            send_message(token, c_chat_id, res_text)
            send_message(token, c_chat_id, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_describe, daemon=True).start()

    elif c_data == "ai_describe_query_char":
        raw_query = c_sess.get("search_target", "custom character")
        reply_or_edit(token, c_chat_id, cb.get("message"), f"🔍 <i>ИИ находит точные теги внешности для '{html.escape(raw_query.title())}'... (~4-6 сек)</i>")

        def _bg_query_describe():
            tags = describe_character_by_name(raw_query)
            c_sess["char_name"] = raw_query.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"✅ <b>Персонаж '{html.escape(raw_query.title())}' успешно обработан ИИ!</b>\n\n"
                f"<b>Danbooru-теги:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"Теги применены к вашей сессии. Нажмите кнопку ниже для генерации:"
            )
            t_main, m_main = make_main_menu(c_sess, user_id=u_id, username=u_name)
            send_message(token, c_chat_id, res_text)
            send_message(token, c_chat_id, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_query_describe, daemon=True).start()

    # 5. ОНЛАЙН ПОИСК
    elif c_data == "start_search_char":
        c_sess["state"] = "awaiting_char_query"
        save_sessions()
        text = (
            "🔍 <b>ОНЛАЙН ПОИСК ПЕРСОНАЖА</b>\n\n"
            "Напишите имя персонажа или название игры на английском в чат.\n"
            "Примеры: <i>Jane Doe (Zenless Zone Zero), tifa, ahri, 2b, raven, loona, toriel, miku...</i>"
        )
        markup = {"inline_keyboard": [[{"text": "◀️ Отмена / Назад", "callback_data": "menu_char"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "start_search_pose":
        c_sess["state"] = "awaiting_pose_query"
        save_sessions()
        text = (
            "🔍 <b>ОНЛАЙН ПОИСК ПОЗЫ</b>\n\n"
            "Напишите позу или действие на английском в чат.\n"
            "Примеры: sit, lying, all fours, kneeling, arch, back, standing, lean..."
        )
        markup = {"inline_keyboard": [[{"text": "◀️ Отмена / Назад", "callback_data": "menu_pose"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "start_search_env":
        c_sess["state"] = "awaiting_env_query"
        save_sessions()
        text = (
            "🔍 <b>ОНЛАЙН ПОИСК ОКРУЖЕНИЯ</b>\n\n"
            "Напишите фон или локацию на английском в чат.\n"
            "Примеры: ruins, bedroom, beach, forest, cyberpunk city, dungeon, bathhouse, classroom, throne room..."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "❌ Без окружения (Очистить)", "callback_data": "clear_env"}],
                [{"text": "◀️ Отмена / Назад", "callback_data": "menu_env"}]
            ]
        }
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "clear_env":
        c_sess["env_name"] = "Без окружения"
        c_sess["env_prompt"] = ""
        c_sess["state"] = "idle"
        save_sessions()
        t, m = make_env_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    # При выборе персонажа автоматически запрашиваем точное описание внешности у ИИ
    elif c_data.startswith("select_char_"):
        items = stored_searches.get(f"{c_chat_id}_char", [])
        try:
            idx = int(c_data.replace("select_char_", ""))
            if not items or idx < 0 or idx >= len(items):
                api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "⚠️ Результаты поиска устарели. Повторите поиск.", "show_alert": False})
                send_message(token, c_chat_id, "⚠️ Результаты поиска устарели. Пожалуйста, выполните поиск заново.")
                t, m = make_char_menu(c_sess)
                reply_or_edit(token, c_chat_id, cb.get("message"), t, m)
                return
            item = items[idx]
        except Exception:
            api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id})
            t, m = make_char_menu(c_sess)
            reply_or_edit(token, c_chat_id, cb.get("message"), t, m)
            return

        char_raw = item[0]
        reply_or_edit(token, c_chat_id, cb.get("message"), f"🔍 <i>ИИ находит точные теги внешности для '{html.escape(char_raw.title())}'... (~4-6 сек)</i>")

        def _bg_select_ai():
            tags = describe_character_by_name(char_raw)
            c_sess["char_name"] = char_raw.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"✅ <b>Персонаж '{html.escape(char_raw.title())}' выбран!</b>\n\n"
                f"<b>Danbooru-теги внешности (ИИ):</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"Теперь вы можете нажать <b>[🚀 СГЕНЕРИРОВАТЬ АРТ]</b>."
            )
            t_main, m_main = make_main_menu(c_sess, user_id=u_id, username=u_name)
            send_message(token, c_chat_id, res_text)
            send_message(token, c_chat_id, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_select_ai, daemon=True).start()

    elif c_data.startswith("select_pose_"):
        items = stored_searches.get(f"{c_chat_id}_pose", [])
        try:
            idx = int(c_data.replace("select_pose_", ""))
            if not items or idx < 0 or idx >= len(items):
                api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "⚠️ Результаты поиска устарели. Повторите поиск.", "show_alert": False})
                send_message(token, c_chat_id, "⚠️ Результаты поиска устарели. Пожалуйста, выполните поиск заново.")
                t, m = make_pose_menu(c_sess)
                reply_or_edit(token, c_chat_id, cb.get("message"), t, m)
                return
            item = items[idx]
        except Exception:
            api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id})
            t, m = make_pose_menu(c_sess)
            reply_or_edit(token, c_chat_id, cb.get("message"), t, m)
            return

        c_sess["pose_name"] = item[0].title()
        tag_escaped = item[1].replace("(", "\\(").replace(")", "\\)").replace("_", " ")
        c_sess["pose_prompt"] = f"{tag_escaped}, looking at viewer"
        c_sess["state"] = "idle"
        save_sessions()
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("select_env_"):
        items = stored_searches.get(f"{c_chat_id}_env", [])
        try:
            idx = int(c_data.replace("select_env_", ""))
            if not items or idx < 0 or idx >= len(items):
                api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "⚠️ Результаты поиска устарели. Повторите поиск.", "show_alert": False})
                send_message(token, c_chat_id, "⚠️ Результаты поиска устарели. Пожалуйста, выполните поиск заново.")
                t, m = make_env_menu(c_sess)
                reply_or_edit(token, c_chat_id, cb.get("message"), t, m)
                return
            item = items[idx]
        except Exception:
            api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id})
            t, m = make_env_menu(c_sess)
            reply_or_edit(token, c_chat_id, cb.get("message"), t, m)
            return

        c_sess["env_name"] = item[0].title()
        tag_escaped = item[1].replace("(", "\\(").replace(")", "\\)").replace("_", " ")
        c_sess["env_prompt"] = tag_escaped
        c_sess["state"] = "idle"
        save_sessions()
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    # Применение введенного текста с автоматическим уточнением внешности через ИИ
    elif c_data == "custom_char_apply":
        raw_query = c_sess.get("search_target", "custom character")
        reply_or_edit(token, c_chat_id, cb.get("message"), f"🔍 <i>ИИ находит точные теги внешности для '{html.escape(raw_query.title())}'... (~4-6 сек)</i>")

        def _bg_apply_ai():
            tags = describe_character_by_name(raw_query)
            c_sess["char_name"] = raw_query.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"✅ <b>Персонаж '{html.escape(raw_query.title())}' выбран!</b>\n\n"
                f"<b>Danbooru-теги внешности (ИИ):</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"Теперь вы можете нажать <b>[🚀 СГЕНЕРИРОВАТЬ АРТ]</b>."
            )
            t_main, m_main = make_main_menu(c_sess, user_id=u_id, username=u_name)
            send_message(token, c_chat_id, res_text)
            send_message(token, c_chat_id, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_apply_ai, daemon=True).start()

    elif c_data == "custom_pose_apply":
        raw_query = c_sess.get("search_target", "custom pose")
        c_sess["pose_name"] = raw_query.title()
        c_sess["pose_prompt"] = f"{raw_query}, looking at viewer"
        c_sess["state"] = "idle"
        save_sessions()
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "custom_env_apply":
        raw_query = c_sess.get("search_target", "custom environment")
        c_sess["env_name"] = raw_query.title()
        c_sess["env_prompt"] = raw_query
        c_sess["state"] = "idle"
        save_sessions()
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    # 6. КАСТОМНЫЙ ПРОМТ И МАГАЗИН STARS
    elif c_data == "menu_custom_prompt":
        c_sess["state"] = "awaiting_custom_prompt"
        save_sessions()
        text = (
            "✍️ <b>РЕЖИМ СВОЕГО ПРОМТА</b>\n\n"
            "В этом режиме вы сами задаете все детали желаемого арта: персонажа, одежду или её отсутствие, ракурс, действие и окружение.\n\n"
            "Бот не добавляет принудительных тегов одежды или наготы, а сохраняет только фирменный стиль: <code>gummyflux, cstyle, &lt;lora:gummyflux_v2:0.95&gt;</code>.\n\n"
            "Отправьте ваш промт на русском или английском языке сообщением прямо в чат:"
        )
        kb = [[{"text": "◀️ Отмена / Назад в меню", "callback_data": "menu_main"}]]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "action_buy_stars":
        t, m = render_buy_stars_menu()
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "menu_referral":
        t, m = make_referral_menu(u_id, BOT_USERNAME)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("buy_pkg_"):
        pkg_key = c_data.replace("buy_pkg_", "")
        pkg = STARS_PACKAGES.get(pkg_key)
        if pkg:
            invoice_payload = {
                "chat_id": c_chat_id,
                "title": f"Пакет: {pkg['title']}",
                "description": f"Покупка {pkg['count']} дополнительных генераций артов в GummyFlux без ограничений по времени.",
                "payload": f"stars_pkg_{pkg_key}_{u_id}_{int(time.time())}",
                "provider_token": "",
                "currency": "XTR",
                "prices": json.dumps([{"label": f"{pkg['count']} ген.", "amount": pkg['stars']}])
            }
            api_call(token, "sendInvoice", invoice_payload)

    # 7. ГЕНЕРАЦИЯ АРТА (С ОБЯЗАТЕЛЬНЫМ ПОДТВЕРЖДЕНИЕМ)
    elif c_data == "action_generate":
        t, m = make_confirm_generation_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "confirm_exec_generate":
        with active_lock:
            if u_id in active_generations:
                send_message(token, c_chat_id, "Ваш запрос уже находится в работе или в очереди.")
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(token, c_chat_id, f"Достигнут дневной лимит генераций (осталось {f_left} из {u_base}, бонусных: {b_left}). Вы можете приобрести дополнительную генерацию со скидкой по кнопке в меню или дождаться полуночи.")
                return

            active_generations.add(u_id)

        try:
            is_nsfw = c_sess.get("mode") == "nsfw"
            prompt_parts = [c_sess.get("char_prompt", "1girl, solo"), c_sess.get("pose_prompt", "looking at viewer")]
            if c_sess.get("env_prompt"):
                prompt_parts.append(c_sess["env_prompt"])
            prompt = ", ".join(p for p in prompt_parts if p)

            w = c_sess.get("width", 832)
            h = c_sess.get("height", 1216)
            
            q_pos = generation_queue.qsize() + 1
            reply_or_edit(token, c_chat_id, cb.get("message"), f"⏳ <b>Запрос подтвержден и добавлен в очередь!</b>\nПозиция в очереди: {q_pos}")

            steps = int(c_sess.get("steps", 20))
            if not is_admin(u_id, u_name):
                steps = max(15, min(25, steps))
            model = c_sess.get("model", DEFAULT_MODEL)

            c_sess["last_is_custom"] = False
            save_sessions()
            generation_queue.put({
                "token": token,
                "chat_id": c_chat_id,
                "user_id": u_id,
                "username": u_name,
                "first_name": u_fname,
                "prompt": prompt,
                "is_nsfw": is_nsfw,
                "with_partner": (c_sess.get("partner_mode") == "with_male"),
                "width": w,
                "height": h,
                "char_name": c_sess.get('char_name', 'Персонаж'),
                "pose_name": c_sess.get('pose_name', 'Поза'),
                "env_name": c_sess.get('env_name', 'Окружение'),
                "is_custom": False,
                "steps": steps,
                "model": model,
                "char_gender": c_sess.get("char_gender", "female"),
                "cfg_scale": c_sess.get("cfg_scale", DEFAULT_CFG_SCALE),
                "consumed_type": consumed_type
            })
        except Exception as e:
            with active_lock:
                active_generations.discard(u_id)
            refund_user_generation(u_id, consumed_type)
            send_message(token, c_chat_id, f"Произошла ошибка при постановке задачи в очередь: {e}")

    elif c_data == "confirm_exec_custom":
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "Промт не найден или был отменен.", reply_markup={"inline_keyboard": [[{"text": "◀️ В главное меню", "callback_data": "menu_main"}]]})
            return

        with active_lock:
            if u_id in active_generations:
                send_message(token, c_chat_id, "Ваш запрос уже находится в работе или в очереди.")
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(token, c_chat_id, f"Достигнут дневной лимит генераций (осталось {f_left} из {u_base}, бонусных: {b_left}). Вы можете приобрести дополнительную генерацию со скидкой по кнопке в меню или дождаться полуночи.")
                return

            active_generations.add(u_id)

        try:
            is_nsfw = c_sess.get("mode") == "nsfw"
            w = c_sess.get("width", 832)
            h = c_sess.get("height", 1216)
            steps = int(c_sess.get("steps", 20))
            if not is_admin(u_id, u_name):
                steps = max(15, min(25, steps))
            model = c_sess.get("model", DEFAULT_MODEL)

            q_pos = generation_queue.qsize() + 1
            reply_or_edit(token, c_chat_id, cb.get("message"), f"⏳ <b>Кастомный запрос подтвержден и принят в очередь!</b>\nПозиция в очереди: {q_pos}")

            c_sess["last_is_custom"] = True
            c_sess["last_custom_prompt"] = raw_prompt
            save_sessions()

            generation_queue.put({
                "token": token,
                "chat_id": c_chat_id,
                "user_id": u_id,
                "username": u_name,
                "first_name": u_fname,
                "prompt": raw_prompt,
                "is_nsfw": is_nsfw,
                "with_partner": (c_sess.get("partner_mode") == "with_male"),
                "width": w,
                "height": h,
                "char_name": "Кастомный арт",
                "pose_name": "Своя поза",
                "env_name": "Свое окружение",
                "is_custom": True,
                "steps": steps,
                "model": model,
                "char_gender": c_sess.get("char_gender", "female"),
                "cfg_scale": c_sess.get("cfg_scale", DEFAULT_CFG_SCALE),
                "consumed_type": consumed_type
            })
        except Exception as e:
            with active_lock:
                active_generations.discard(u_id)
            refund_user_generation(u_id, consumed_type)
            send_message(token, c_chat_id, f"Произошла ошибка при постановке задачи в очередь: {e}")

    elif c_data == "confirm_exec_custom_ai":
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "Промт не найден или был отменен.", reply_markup={"inline_keyboard": [[{"text": "◀️ В главное меню", "callback_data": "menu_main"}]]})
            return

        with active_lock:
            if u_id in active_generations:
                send_message(token, c_chat_id, "Ваш запрос уже находится в работе или в очереди.")
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(token, c_chat_id, f"Достигнут дневной лимит генераций (осталось {f_left} из {u_base}, бонусных: {b_left}). Вы можете приобрести дополнительную генерацию со скидкой по кнопке в меню или дождаться полуночи.")
                return

            active_generations.add(u_id)

        reply_or_edit(token, c_chat_id, cb.get("message"), f"✨ <i>ИИ детально прорабатывает и обогащает промт для '{html.escape(raw_prompt[:60])}' (~3-5 сек)...</i>")

        def _bg_exec_ai_custom():
            try:
                try:
                    if len(raw_prompt.split()) <= 4 and "," not in raw_prompt:
                        enhanced_tags = describe_character_by_name(raw_prompt)
                    else:
                        enhanced_tags = enhance_prompt_with_ai(raw_prompt)
                except Exception as e:
                    print(f"Error enhancing prompt with AI: {e}", flush=True)
                    enhanced_tags = raw_prompt

                is_nsfw = c_sess.get("mode") == "nsfw"
                w = c_sess.get("width", 832)
                h = c_sess.get("height", 1216)
                steps = int(c_sess.get("steps", 20))
                if not is_admin(u_id, u_name):
                    steps = max(15, min(25, steps))
                model = c_sess.get("model", DEFAULT_MODEL)

                c_sess["last_is_custom"] = True
                c_sess["last_custom_prompt"] = enhanced_tags
                save_sessions()

                q_pos = generation_queue.qsize() + 1
                send_message(
                    token, c_chat_id,
                    f"⏳ <b>Запрос детально составлен через ИИ и принят в очередь!</b>\nПозиция: {q_pos}\n\n"
                    f"<b>Danbooru-промт ИИ:</b>\n<code>{html.escape(enhanced_tags[:200])}...</code>"
                )

                generation_queue.put({
                    "token": token,
                    "chat_id": c_chat_id,
                    "user_id": u_id,
                    "username": u_name,
                    "first_name": u_fname,
                    "prompt": enhanced_tags,
                    "is_nsfw": is_nsfw,
                    "with_partner": (c_sess.get("partner_mode") == "with_male"),
                    "width": w,
                    "height": h,
                    "char_name": "Кастомный арт (ИИ)",
                    "pose_name": "Своя поза",
                    "env_name": "Свое окружение",
                    "is_custom": True,
                    "steps": steps,
                    "model": model,
                    "char_gender": c_sess.get("char_gender", "female"),
                    "cfg_scale": c_sess.get("cfg_scale", DEFAULT_CFG_SCALE),
                    "consumed_type": consumed_type
                })
            except Exception as e:
                with active_lock:
                    active_generations.discard(u_id)
                refund_user_generation(u_id, consumed_type)
                send_message(token, c_chat_id, f"Произошла ошибка при обработке запроса ИИ: {e}")

        threading.Thread(target=_bg_exec_ai_custom, daemon=True).start()

    elif c_data == "quick_rerun":
        with active_lock:
            if u_id in active_generations:
                api_call(token, "answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "⏳ Ваша предыдущая генерация еще в процессе!",
                    "show_alert": False
                })
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(
                    token, c_chat_id,
                    f"Достигнут дневной лимит генераций (осталось {f_left} из {u_base}, бонусных: {b_left}). "
                    "Вы можете приобрести дополнительные генерации по кнопке в меню или дождаться полуночи."
                )
                return

            active_generations.add(u_id)

        try:
            is_custom = c_sess.get("last_is_custom", False)
            is_nsfw = c_sess.get("mode") == "nsfw"
            w = c_sess.get("width", 832)
            h = c_sess.get("height", 1216)
            steps = int(c_sess.get("steps", 20))
            if not is_admin(u_id, u_name):
                steps = max(15, min(25, steps))
            model = c_sess.get("model", DEFAULT_MODEL)
            q_pos = generation_queue.qsize() + 1

            if is_custom:
                prompt = c_sess.get("last_custom_prompt") or c_sess.get("pending_custom_prompt", "")
                char_name = "Кастомный арт"
                pose_name = "Своя поза"
                env_name = "Свое окружение"
                send_message(token, c_chat_id, f"⏳ <b>Повторная генерация кастомного арта принята в очередь!</b>\nПозиция: {q_pos}")
            else:
                prompt_parts = [c_sess.get("char_prompt", "1girl, solo"), c_sess.get("pose_prompt", "looking at viewer")]
                if c_sess.get("env_prompt"):
                    prompt_parts.append(c_sess["env_prompt"])
                prompt = ", ".join(p for p in prompt_parts if p)
                char_name = c_sess.get('char_name', 'Персонаж')
                pose_name = c_sess.get('pose_name', 'Поза')
                env_name = c_sess.get('env_name', 'Окружение')
                send_message(token, c_chat_id, f"⏳ <b>Новый вариант {html.escape(char_name)} принят в очередь!</b>\nПозиция: {q_pos}")

            generation_queue.put({
                "token": token,
                "chat_id": c_chat_id,
                "user_id": u_id,
                "username": u_name,
                "first_name": u_fname,
                "prompt": prompt,
                "is_nsfw": is_nsfw,
                "with_partner": (c_sess.get("partner_mode") == "with_male"),
                "width": w,
                "height": h,
                "char_name": char_name,
                "pose_name": pose_name,
                "env_name": env_name,
                "is_custom": is_custom,
                "steps": steps,
                "model": model,
                "char_gender": c_sess.get("char_gender", "female"),
                "cfg_scale": c_sess.get("cfg_scale", DEFAULT_CFG_SCALE),
                "consumed_type": consumed_type
            })
        except Exception as e:
            with active_lock:
                active_generations.discard(u_id)
            refund_user_generation(u_id, consumed_type)
            send_message(token, c_chat_id, f"Произошла ошибка при постановке задачи в очередь: {e}")

    elif c_data == "quick_toggle_mode":
        with active_lock:
            if u_id in active_generations:
                api_call(token, "answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "⏳ Ваша предыдущая генерация еще в процессе!",
                    "show_alert": False
                })
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(
                    token, c_chat_id,
                    f"Достигнут дневной лимит генераций (осталось {f_left} из {u_base}, бонусных: {b_left}). "
                    "Вы можете приобрести дополнительные генерации по кнопке в меню или дождаться полуночи."
                )
                return

            active_generations.add(u_id)

        try:
            new_mode = "sfw" if c_sess.get("mode") == "nsfw" else "nsfw"
            c_sess["mode"] = new_mode
            save_sessions()
            is_nsfw = (new_mode == "nsfw")
            mode_label = "🔥 Без одежды (NSFW)" if is_nsfw else "👗 В одежде (SFW)"

            is_custom = c_sess.get("last_is_custom", False)
            w = c_sess.get("width", 832)
            h = c_sess.get("height", 1216)
            steps = int(c_sess.get("steps", 20))
            if not is_admin(u_id, u_name):
                steps = max(15, min(25, steps))
            model = c_sess.get("model", DEFAULT_MODEL)
            q_pos = generation_queue.qsize() + 1

            if is_custom:
                prompt = c_sess.get("last_custom_prompt") or c_sess.get("pending_custom_prompt", "")
                char_name = "Кастомный арт"
                pose_name = "Своя поза"
                env_name = "Свое окружение"
                send_message(token, c_chat_id, f"⏳ <b>Режим переключен: {mode_label}!</b>\nКастомный арт принят в очередь (позиция: {q_pos})...")
            else:
                prompt_parts = [c_sess.get("char_prompt", "1girl, solo"), c_sess.get("pose_prompt", "looking at viewer")]
                if c_sess.get("env_prompt"):
                    prompt_parts.append(c_sess["env_prompt"])
                prompt = ", ".join(p for p in prompt_parts if p)
                char_name = c_sess.get('char_name', 'Персонаж')
                pose_name = c_sess.get('pose_name', 'Поза')
                env_name = c_sess.get('env_name', 'Окружение')
                send_message(token, c_chat_id, f"⏳ <b>Режим переключен: {mode_label}!</b>\nГенерация {html.escape(char_name)} принята в очередь (позиция: {q_pos})...")

            generation_queue.put({
                "token": token,
                "chat_id": c_chat_id,
                "user_id": u_id,
                "username": u_name,
                "first_name": u_fname,
                "prompt": prompt,
                "is_nsfw": is_nsfw,
                "with_partner": (c_sess.get("partner_mode") == "with_male"),
                "width": w,
                "height": h,
                "char_name": char_name,
                "pose_name": pose_name,
                "env_name": env_name,
                "is_custom": is_custom,
                "steps": steps,
                "model": model,
                "char_gender": c_sess.get("char_gender", "female"),
                "cfg_scale": c_sess.get("cfg_scale", DEFAULT_CFG_SCALE),
                "consumed_type": consumed_type
            })
        except Exception as e:
            with active_lock:
                active_generations.discard(u_id)
            refund_user_generation(u_id, consumed_type)
            send_message(token, c_chat_id, f"Произошла ошибка при постановке задачи в очередь: {e}")

    elif c_data == "custom_search_char":
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "Запрос не найден.", reply_markup={"inline_keyboard": [[{"text": "◀️ В меню", "callback_data": "menu_main"}]]})
            return
        reply_or_edit(token, c_chat_id, cb.get("message"), f"🔍 <i>Определяю персонажа '{html.escape(raw_prompt)}'...</i>")
        def _bg_char_from_prompt():
            tags = describe_character_by_name(raw_prompt)
            c_sess["char_name"] = raw_prompt.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            t, m = make_char_menu(c_sess)
            send_message(token, c_chat_id, f"✅ Персонаж <b>{html.escape(raw_prompt.title())}</b> успешно установлен!\n\nТеги: <code>{html.escape(tags)}</code>")
            send_message(token, c_chat_id, t, reply_markup=m)
        threading.Thread(target=_bg_char_from_prompt, daemon=True).start()

    elif c_data == "custom_enhance_ai":
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "Запрос не найден.", reply_markup={"inline_keyboard": [[{"text": "◀️ В меню", "callback_data": "menu_main"}]]})
            return
        reply_or_edit(token, c_chat_id, cb.get("message"), "✨ <i>ИИ детально прорабатывает и расширяет промт... (~3-5 сек)...</i>")

        def _bg_enhance():
            enhanced = enhance_prompt_with_ai(raw_prompt)
            c_sess["pending_custom_prompt"] = enhanced
            save_sessions()
            t_conf, m_conf = make_confirm_custom_menu(enhanced, c_sess, user_id=u_id, username=u_name)
            send_message(
                token, c_chat_id,
                f"✅ <b>Промт детализирован ИИ!</b>\n\n"
                f"<b>Подробный набор тегов:</b>\n<code>{html.escape(enhanced)}</code>"
            )
            send_message(token, c_chat_id, t_conf, reply_markup=m_conf)

        threading.Thread(target=_bg_enhance, daemon=True).start()

    elif c_data == "cancel_custom_prompt":
        c_sess["pending_custom_prompt"] = ""
        c_sess["state"] = "idle"
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)


    # 8. ПАНЕЛЬ АДМИНИСТРАТОРА
    elif c_data == "admin_main":
        c_sess["state"] = "idle"
        t, m = make_admin_menu()
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "admin_stats":
        t, m = render_admin_stats()
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_users"):
        page = 0
        if c_data.startswith("admin_users_page_"):
            try:
                page = int(c_data.replace("admin_users_page_", ""))
            except Exception:
                page = 0
        t, m = render_admin_users(page)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "admin_search_user":
        c_sess["state"] = "awaiting_admin_search_user"
        save_sessions()
        text = (
            "🔍 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"
            "Отправьте в чат @username, числовой Telegram ID или имя пользователя:"
        )
        kb = [[{"text": "◀️ Отмена", "callback_data": "admin_users_page_0"}]]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data.startswith("admin_user_"):
        target_uid = c_data.replace("admin_user_", "")
        t, m = render_admin_user_card(target_uid)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_edit_base_"):
        target_uid = c_data.replace("admin_edit_base_", "")
        t, m = render_admin_edit_base_menu(target_uid)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_set_base_"):
        parts = c_data.replace("admin_set_base_", "").split("_")
        target_uid = parts[0]
        new_lim = int(parts[1])
        set_user_base_limit(target_uid, new_lim)
        t, m = render_admin_user_card(target_uid)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_custom_base_"):
        target_uid = c_data.replace("admin_custom_base_", "")
        c_sess["state"] = "awaiting_custom_base_limit"
        c_sess["target_user_id"] = target_uid
        save_sessions()
        text = (
            f"✏️ <b>ВВЕДИТЕ БАЗОВЫЙ ЛИМИТ В ЧАТ</b>\n\n"
            f"Для пользователя ID {html.escape(target_uid)}.\n"
            "Напишите число бесплатных генераций в день (например, 5, 10 или 50):"
        )
        kb = [[{"text": "◀️ Отмена", "callback_data": f"admin_user_{target_uid}"}]]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data.startswith("admin_grant_"):
        target_uid = c_data.replace("admin_grant_", "")
        t, m = render_admin_grant_menu(target_uid)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_add_grant_"):
        parts = c_data.replace("admin_add_grant_", "").split("_")
        target_uid = parts[0]
        amount_val = parts[1]
        add_user_bonus_generations(target_uid, amount_val)
        if amount_val != "reset":
            try:
                send_message(token, target_uid, f"🎁 Администратор начислил вам +{amount_val} дополнительных генераций артов! Приятного творчества!")
            except Exception:
                pass
        t, m = render_admin_user_card(target_uid)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_custom_grant_"):
        target_uid = c_data.replace("admin_custom_grant_", "")
        c_sess["state"] = "awaiting_custom_grant"
        c_sess["target_user_id"] = target_uid
        save_sessions()
        text = (
            f"🎁 <b>ВВЕДИТЕ КОЛИЧЕСТВО ГЕНЕРАЦИЙ В ЧАТ</b>\n\n"
            f"Для пользователя ID {html.escape(target_uid)}.\n"
            "Напишите число бонусных генераций для начисления (например, 10 или 25):"
        )
        kb = [[{"text": "◀️ Отмена", "callback_data": f"admin_user_{target_uid}"}]]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data.startswith("admin_reset_daily_"):
        target_uid = c_data.replace("admin_reset_daily_", "")
        reset_user_daily_count(target_uid)
        t, m = render_admin_user_card(target_uid)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_hist"):
        page = 0
        if c_data.startswith("admin_hist_page_"):
            try:
                page = int(c_data.replace("admin_hist_page_", ""))
            except Exception:
                page = 0
        t, m = render_admin_history(page)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data.startswith("admin_view_art_"):
        art_id = c_data.replace("admin_view_art_", "")
        db = load_db()
        found = False
        for h in db.get("history", []):
            if h.get("id") == art_id:
                img_p = h.get("image_path", "")
                if img_p and os.path.exists(img_p):
                    try:
                        with open(img_p, "rb") as f_img:
                            img_bytes = f_img.read()
                        uname = f"@{h.get('username')}" if h.get("username") else f"ID {h.get('user_id')}"
                        mode_txt = "Uncensored" if h.get("mode") == "nsfw" else "SFW"
                        caption = (
                            f"🖼 Арт [{h.get('id', '')}]\n"
                            f"👤 Автор: {html.escape(str(uname))} (ID: {h.get('user_id')})\n"
                            f"🕒 Время: {html.escape(str(h.get('time', '')))}\n"
                            f"⚙️ Параметры: {mode_txt}, {h.get('res')}, {h.get('elapsed')} сек.\n"
                            f"📝 Промт: {html.escape(str(h.get('prompt', ''))[:400])}"
                        )
                        kb = [[{"text": "◀️ Назад к истории", "callback_data": "admin_hist_page_0"}]]
                        send_photo(token, c_chat_id, img_bytes, caption=caption, reply_markup={"inline_keyboard": kb})
                        found = True
                        break
                    except Exception as e:
                        send_message(token, c_chat_id, f"Ошибка чтения файла: {e}")
                        found = True
                        break
        if not found:
            send_message(token, c_chat_id, "Файл изображения не найден на диске (генерация была до включения архивации).")

    elif c_data == "admin_confirm_reset_all_view":
        db = load_db()
        total_u = len(db.get("users", {}))
        text = (
            "⚠️ <b>МАССОВЫЙ СБРОС ЛИМИТОВ ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n\n"
            f"Вы собираетесь обнулить суточный счетчик генераций для всех пользователей бота (всего в базе: {total_u}).\n\n"
            "Каждому пользователю будет отправлено персональное уведомление в чат с ботом о том, что его суточный лимит снова полон.\n\n"
            "Подтвердить сброс?"
        )
        kb = [
            [{"text": "✅ Да, сбросить всем и разослать", "callback_data": "admin_do_reset_all"}],
            [{"text": "◀️ Отмена / Назад", "callback_data": "admin_users_page_0"}]
        ]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "admin_do_reset_all":
        reply_or_edit(token, c_chat_id, cb.get("message"), "⏳ <b>Выполняется сброс лимитов и рассылка уведомлений...</b>\nПожалуйста, подождите завершения операции.")
        reset_all_users_daily_limits_async(token, c_chat_id, send_message)

    elif c_data == "admin_safe_restart":
        perform_safe_reload(token, c_chat_id)

    elif c_data == "admin_confirm_shutdown":
        text = (
            "⚠️ <b>ВЫКЛЮЧЕНИЕ БОТА</b>\n\n"
            "Вы действительно хотите полностью отключить Telegram бота?\n\n"
            "После выключения сервис перестанет отвечать на сообщения и обрабатывать запросы, "
            "пока его не запустят заново на компьютере.\n\n"
            "Подтвердить выключение?"
        )
        kb = [
            [{"text": "🛑 Да, полностью выключить бота", "callback_data": "admin_do_shutdown"}],
            [{"text": "◀️ Отмена / Назад", "callback_data": "admin_main"}]
        ]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "admin_do_shutdown":
        reply_or_edit(token, c_chat_id, cb.get("message"), "🛑 <b>Инициирован процесс выключения бота...</b>")
        perform_safe_shutdown(token, c_chat_id, reason="Команда из админ-панели Telegram")

    elif c_data == "admin_messages":
        t, m = render_admin_messages()
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

def handle_message(token, msg, stored_searches):
    m_chat = str(msg["chat"]["id"])
    msg_user = msg.get("from", {})
    u_id = str(msg_user.get("id", m_chat))
    u_name = msg_user.get("username", "")
    u_fname = msg_user.get("first_name", "")

    touch_user(u_id, u_name, u_fname)
    m_sess = get_session(m_chat)

    # 1. ОБРАБОТКА ОПЛАТЫ TELEGRAM STARS
    if "successful_payment" in msg:
        sp = msg["successful_payment"]
        if sp.get("currency") == "XTR":
            amount_stars = sp.get("total_amount", 2)
            payload = sp.get("invoice_payload", "")
            count_to_add = None
            if payload.startswith("stars_pkg_"):
                parts = payload.split("_")
                if len(parts) >= 3 and parts[2] in STARS_PACKAGES:
                    count_to_add = STARS_PACKAGES[parts[2]]["count"]
            if count_to_add is None:
                if amount_stars >= 99:
                    count_to_add = 100
                elif amount_stars >= 55:
                    count_to_add = 50
                elif amount_stars >= 20:
                    count_to_add = 15
                elif amount_stars >= 8:
                    count_to_add = 5
                elif amount_stars >= 2:
                    count_to_add = 1
                else:
                    count_to_add = max(1, amount_stars // 2)

            add_bonus_credits(u_id, count=count_to_add, stars=amount_stars)
            _, free_l, bonus_l, total_l = get_user_limits_status(u_id, u_name)
            send_message(token, m_chat, f"🎉 <b>Оплата {amount_stars} ⭐️ Stars успешно подтверждена!</b>\n\nВам начислено +{count_to_add} дополнительных генераций артов. Всего доступно генераций: {total_l}.")
            t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, t, reply_markup=m)
            return

    # 2. ОБРАБОТКА ИЗОБРАЖЕНИЯ (ПЕРСОНАЖ ПО ФОТО)
    if "photo" in msg and m_sess.get("state") == "awaiting_char_photo":
        photo_list = msg.get("photo", [])
        if photo_list:
            send_message(token, m_chat, "🔍 <i>Загружаю фото и передаю в ИИ для анализа внешности персонажа...</i>")
            
            def _bg_photo_process():
                try:
                    file_id = photo_list[-1]["file_id"]
                    file_path = get_file(token, file_id)
                    if not file_path:
                        send_message(token, m_chat, "Не удалось получить путь к файлу изображения в Telegram.")
                        return

                    img_bytes = download_file(token, file_path)
                    if not img_bytes:
                        send_message(token, m_chat, "Не удалось скачать фото из Telegram.")
                        return

                    char_name, tags = describe_character_by_photo(img_bytes)
                    if not char_name or not tags:
                        send_message(
                            token,
                            m_chat,
                            "❌ Не удалось надёжно разобрать изображение. "
                            "Прежний персонаж сохранён. Попробуйте другое фото или PNG-арт."
                        )
                        return

                    # Пока ИИ работал, пользователь мог отменить операцию или выбрать другое.
                    if m_sess.get("state") != "awaiting_char_photo":
                        return

                    m_sess["char_name"] = char_name
                    m_sess["char_prompt"] = tags
                    m_sess["char_gender"] = (
                        "male" if "1boy" in [t.strip() for t in tags.split(",")]
                        else "female" if "1girl" in [t.strip() for t in tags.split(",")]
                        else m_sess.get("char_gender", "female")
                    )
                    m_sess["state"] = "idle"
                    save_sessions()

                    caption_resp = (
                        f"✅ <b>Персонаж успешно распознан по фото!</b>\n\n"
                        f"👤 <b>Имя / Описание:</b> {html.escape(char_name)}\n"
                        f"📝 <b>Danbooru-теги внешности:</b>\n<code>{html.escape(tags)}</code>\n\n"
                        f"Параметры персонажа установлены в сессию. Нажмите <b>[🚀 СГЕНЕРИРОВАТЬ АРТ]</b> для генерации!"
                    )
                    t_main, m_main = make_main_menu(m_sess, user_id=u_id, username=u_name)
                    send_message(token, m_chat, caption_resp)
                    send_message(token, m_chat, t_main, reply_markup=m_main)
                except Exception as e:
                    send_message(token, m_chat, f"Ошибка при распознавании персонажа по фото: {e}")

            threading.Thread(target=_bg_photo_process, daemon=True).start()
            return

    # 3. ТЕКСТОВЫЕ СООБЩЕНИЯ
    text = msg.get("text", "").strip()
    if not text:
        return

    if not is_admin(u_id, u_name):
        log_message(u_id, u_name, text)

    if text.startswith("/start"):
        m_sess["state"] = "idle"
        parts = text.split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            inviter_id = parts[1].replace("ref_", "").strip()
            success, _ = process_referral(u_id, inviter_id, token, send_message)
            if success:
                welcome_ref = (
                    "🎉 <b>Добро пожаловать в GummyFlux!</b>\n\n"
                    "Вы зарегистрировались по персональному приглашению друга. "
                    "Вам начислена <b>+1 стартовая бонусная генерация</b> сверх лимита!\n\n"
                    "Приятного творчества!"
                )
                send_message(token, m_chat, welcome_ref)

        t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
        send_message(token, m_chat, t, reply_markup=m)

    elif text.startswith("/menu"):
        m_sess["state"] = "idle"
        t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
        send_message(token, m_chat, t, reply_markup=m)

    elif text.startswith("/help"):
        m_sess["state"] = "idle"
        help_text = (
            "ℹ️ <b>Справка по GummyFlux Bot</b>\n\n"
            "• Нажмите <b>/menu</b>, чтобы открыть панель управления генерацией артов.\n"
            "• Вы можете выбрать готового персонажа, позу и окружение или описать персонажа через ИИ и по фото.\n"
            "• Чтобы использовать полностью свой промт, выберите раздел «✍️ Свой кастомный промт» в меню или отправьте описание в чат.\n"
            "• Каждый день вам доступно бесплатное количество генераций, а дополнительные можно приобрести через Telegram Stars или получить за приглашение друзей."
        )
        t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
        send_message(token, m_chat, help_text, reply_markup=m)

    elif text == "/admin" and is_admin(u_id, u_name):
        t, m = make_admin_menu()
        send_message(token, m_chat, t, reply_markup=m)

    elif text in ("/stop", "/shutdown") and is_admin(u_id, u_name):
        send_message(token, m_chat, "🛑 <b>Инициирован процесс выключения бота...</b>")
        perform_safe_shutdown(token, m_chat, reason=f"Команда {text} от администратора")

    elif text == "/restart" and is_admin(u_id, u_name):
        send_message(token, m_chat, "🔄 <b>Инициирован перезапуск бота...</b>")
        perform_safe_reload(token, m_chat)

    elif is_admin(u_id, u_name) and m_sess.get("state") == "awaiting_admin_search_user":
        target_uid, user_obj = find_user_by_query(text)
        if target_uid:
            m_sess["state"] = "idle"
            t, m = render_admin_user_card(target_uid)
            send_message(token, m_chat, t, reply_markup=m)
        else:
            kb = [
                [{"text": "🔍 Попробовать снова", "callback_data": "admin_search_user"}],
                [{"text": "◀️ Назад к пользователям", "callback_data": "admin_users_page_0"}]
            ]
            send_message(token, m_chat, f"Пользователь '{html.escape(text)}' не найден в базе данных бота.", reply_markup={"inline_keyboard": kb})

    elif is_admin(u_id, u_name) and m_sess.get("state") == "awaiting_custom_base_limit":
        target_uid = m_sess.get("target_user_id")
        if text.isdigit() and 0 <= int(text) <= 1000:
            set_user_base_limit(target_uid, int(text))
            m_sess["state"] = "idle"
            t, m = render_admin_user_card(target_uid)
            send_message(token, m_chat, f"✅ Базовый лимит пользователя установлен: {text} ген./день.\n\n" + t, reply_markup=m)
        else:
            kb = [[{"text": "◀️ Отмена", "callback_data": f"admin_user_{target_uid}"}]]
            send_message(token, m_chat, "Пожалуйста, введите число от 0 до 1000.", reply_markup={"inline_keyboard": kb})

    elif is_admin(u_id, u_name) and m_sess.get("state") == "awaiting_custom_grant":
        target_uid = m_sess.get("target_user_id")
        if text.isdigit() and 1 <= int(text) <= 10000:
            add_user_bonus_generations(target_uid, int(text))
            try:
                send_message(token, target_uid, f"🎁 Администратор начислил вам +{text} дополнительных генераций артов! Приятного творчества!")
            except Exception:
                pass
            m_sess["state"] = "idle"
            t, m = render_admin_user_card(target_uid)
            send_message(token, m_chat, f"✅ Пользователю успешно начислено +{text} бонусных генераций!\n\n" + t, reply_markup=m)
        else:
            kb = [[{"text": "◀️ Отмена", "callback_data": f"admin_user_{target_uid}"}]]
            send_message(token, m_chat, "Пожалуйста, введите положительное число от 1 до 10000.", reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_custom_samples":
        if text.isdigit():
            val = int(text)
            if is_admin(u_id, u_name):
                if 5 <= val <= 60:
                    m_sess["steps"] = val
                    m_sess["state"] = "idle"
                    save_sessions()
                    t, m = make_samples_menu(m_sess, user_id=u_id, username=u_name)
                    send_message(token, m_chat, f"✅ Количество шагов семплирования установлено: <b>{val}</b>.\n\n" + t, reply_markup=m)
                else:
                    kb = [[{"text": "◀️ Отмена", "callback_data": "menu_samples"}]]
                    send_message(token, m_chat, "Пожалуйста, введите число шагов от 5 до 60.", reply_markup={"inline_keyboard": kb})
            else:
                if 15 <= val <= 25:
                    m_sess["steps"] = val
                    m_sess["state"] = "idle"
                    save_sessions()
                    t, m = make_samples_menu(m_sess, user_id=u_id, username=u_name)
                    send_message(token, m_chat, f"✅ Количество шагов семплирования установлено: <b>{val}</b>.\n\n" + t, reply_markup=m)
                else:
                    kb = [[{"text": "◀️ Отмена", "callback_data": "menu_samples"}]]
                    send_message(token, m_chat, "Для вашего аккаунта доступно от 15 до 25 шагов.", reply_markup={"inline_keyboard": kb})
        else:
            kb = [[{"text": "◀️ Отмена", "callback_data": "menu_samples"}]]
            min_s, max_s = (5, 60) if is_admin(u_id, u_name) else (15, 25)
            send_message(token, m_chat, f"Пожалуйста, введите корректное число от {min_s} до {max_s}.", reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_custom_cfg":
        try:
            val = float(text.replace(",", ".").strip())
            if 1.0 <= val <= 15.0:
                val = round(val, 1)
                m_sess["cfg_scale"] = val
                m_sess["state"] = "idle"
                save_sessions()
                t, m = make_cfg_menu(m_sess)
                send_message(token, m_chat, f"✅ Параметр силы промпта (CFG Scale) установлен: <b>{val}</b>.\n\n" + t, reply_markup=m)
            else:
                kb = [[{"text": "◀️ Отмена", "callback_data": "menu_cfg"}]]
                send_message(token, m_chat, "Пожалуйста, введите число от <b>1.0</b> до <b>15.0</b>.", reply_markup={"inline_keyboard": kb})
        except ValueError:
            kb = [[{"text": "◀️ Отмена", "callback_data": "menu_cfg"}]]
            send_message(token, m_chat, "Пожалуйста, введите корректное число от <b>1.0</b> до <b>15.0</b> (например: <code>5.5</code> или <code>7.0</code>).", reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_ai_char_name":
        send_message(token, m_chat, f"🔍 <i>ИИ находит описание и четкие Danbooru-теги для '{html.escape(text)}'...</i>")

        def _bg_name_tagging():
            tags = describe_character_by_name(text)
            m_sess["char_name"] = text.title()
            m_sess["char_prompt"] = tags
            m_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"✅ <b>Внешность '{html.escape(text.title())}' сформирована через ИИ!</b>\n\n"
                f"<b>Danbooru-теги:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"Параметры персонажа установлены в сессию."
            )
            t_main, m_main = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, res_text)
            send_message(token, m_chat, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_name_tagging, daemon=True).start()

    elif m_sess.get("state") == "awaiting_char_photo":
        send_message(token, m_chat, "Пожалуйста, отправьте именно изображение персонажа (вложением 'Фото').")

    elif m_sess.get("state") == "awaiting_char_query":
        send_message(token, m_chat, f"🔍 <i>Ищу персонажа '{html.escape(text)}' и составляю подробный Danbooru-промт через ИИ...</i>")

        def _bg_search_and_ai():
            results = search_online_characters(text)
            m_sess["search_target"] = text
            stored_searches[f"{m_chat}_char"] = results

            # Если в базе найден каноничный тег (например, v_(murder_drones)), передаем его ИИ для идеальной точности
            ai_query = text
            if results and results[0][0]:
                ai_query = f"{text} ({results[0][0]})"

            tags = describe_character_by_name(ai_query)
            char_title = results[0][0].title() if results else text.title()

            m_sess["char_name"] = char_title
            m_sess["char_prompt"] = tags
            m_sess["state"] = "idle"
            save_sessions()

            res_text = (
                f"✅ <b>Персонаж '{html.escape(char_title)}' успешно распознан и описан ИИ!</b>\n\n"
                f"<b>Danbooru-теги внешности:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"Параметры персонажа установлены. Нажмите <b>[🚀 СГЕНЕРИРОВАТЬ АРТ]</b> для создания изображения."
            )

            kb = []
            if len(results) > 1:
                alt_row = []
                for idx, r in enumerate(results[1:4], 1):
                    alt_row.append({"text": f"👤 {r[0].title()}", "callback_data": f"select_char_{idx}"})
                if alt_row:
                    kb.append(alt_row)

            t_main, m_main = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, res_text, reply_markup={"inline_keyboard": kb} if kb else None)
            send_message(token, m_chat, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_search_and_ai, daemon=True).start()

    elif m_sess.get("state") == "awaiting_pose_query":
        send_message(token, m_chat, f"Выполняю онлайн поиск позы: '{text}'...")
        results = search_online_poses(text)
        m_sess["search_target"] = text
        stored_searches[f"{m_chat}_pose"] = results

        kb = []
        for idx, r in enumerate(results):
            kb.append([{"text": f"[{r[0].title()}]", "callback_data": f"select_pose_{idx}"}])

        kb.append([{"text": f"[Использовать '{text}' как есть]", "callback_data": "custom_pose_apply"}])
        kb.append([{"text": "◀️ Назад в выбор позы", "callback_data": "menu_pose"}])

        reply_text = f"Результаты поиска поз для '{text}':\nВыберите найденную позу или примените введенный текст:"
        send_message(token, m_chat, reply_text, reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_env_query":
        send_message(token, m_chat, f"Выполняю онлайн поиск окружения: '{text}'...")
        results = search_online_environment(text)
        m_sess["search_target"] = text
        stored_searches[f"{m_chat}_env"] = results

        kb = []
        for idx, r in enumerate(results):
            kb.append([{"text": f"[{r[0].title()}]", "callback_data": f"select_env_{idx}"}])

        kb.append([{"text": f"[Использовать '{text}' как есть]", "callback_data": "custom_env_apply"}])
        kb.append([{"text": "❌ Без окружения (Очистить)", "callback_data": "clear_env"}])
        kb.append([{"text": "◀️ Назад в выбор окружения", "callback_data": "menu_env"}])

        reply_text = f"Результаты поиска окружения для '{text}':\nВыберите найденную локацию или примените введенный текст:"
        send_message(token, m_chat, reply_text, reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_resolution":
        clean_res = text.lower().replace("х", "x").replace("*", "x").replace(" ", "")
        parts = clean_res.split("x")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            w = int(parts[0])
            h = int(parts[1])
            if w > 1500 or h > 1500:
                send_message(token, m_chat, "Ошибка: стороны разрешения не могут превышать 1500 пикселей.")
            elif w < 512 or h < 512:
                send_message(token, m_chat, "Ошибка: минимальный размер стороны составляет 512 пикселей.")
            else:
                w = (w // 64) * 64
                h = (h // 64) * 64
                w = min(w, 1472)
                h = min(h, 1472)
                m_sess["width"] = w
                m_sess["height"] = h
                m_sess["state"] = "idle"
                save_sessions()
                send_message(token, m_chat, f"Установлено разрешение: {w}x{h}.")
                t, m = make_settings_menu(m_sess, user_id=u_id, username=u_name)
                send_message(token, m_chat, t, reply_markup=m)
        else:
            send_message(token, m_chat, "Неверный формат. Введите размеры в формате ШИРИНАxВЫСОТА (например, 896x1152).")

    else:
        # Проверяем, является ли сообщение обычным приветствием или вопросом
        clean_low = text.lower().strip()
        greetings = {"привет", "хай", "здравствуйте", "добрый день", "добрый вечер", "ку", "hello", "hi", "hey", "старт", "помощь", "help", "меню"}
        if clean_low in greetings:
            m_sess["state"] = "idle"
            t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, "Привет! Для выбора персонажа, позы или создания арта используйте меню:", reply_markup=m)
        else:
            # Произвольный текст / кастомный промт: не запускаем генерацию сразу, а спрашиваем подтверждение!
            m_sess["pending_custom_prompt"] = text
            m_sess["state"] = "idle"
            t, m = make_confirm_custom_menu(text, m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, t, reply_markup=m)

