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
    log_message, process_referral, add_pc_notify, get_pc_notifies
)
from bot.sd_client import is_backend_online
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

def check_pc_online_or_notify(token, chat_id, message_obj=None):
    if not is_backend_online():
        text = (
            "рџ”Њ <b>Р“РµРЅРµСЂР°С†РёСЏ РІСЂРµРјРµРЅРЅРѕ РЅРµРґРѕСЃС‚СѓРїРЅР°</b>\n\n"
            "РљРѕРјРїСЊСЋС‚РµСЂ СЃ РЅРµР№СЂРѕСЃРµС‚СЊСЋ СЃРµР№С‡Р°СЃ РІС‹РєР»СЋС‡РµРЅ РёР»Рё РЅР°С…РѕРґРёС‚СЃСЏ РІ СЂРµР¶РёРјРµ СЃРЅР°.\n"
            "РќР°Р¶РјРёС‚Рµ РєРЅРѕРїРєСѓ РЅРёР¶Рµ, Рё Р±РѕС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РѕРїРѕРІРµСЃС‚РёС‚ РІР°СЃ Р·РґРµСЃСЊ, РєР°Рє С‚РѕР»СЊРєРѕ РџРљ РІРєР»СЋС‡РёС‚СЃСЏ Рё РіРµРЅРµСЂР°С†РёСЏ СЃС‚Р°РЅРµС‚ РґРѕСЃС‚СѓРїРЅР°!"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "рџ”” РћРїРѕРІРµСЃС‚РёС‚СЊ, РєРѕРіРґР° РџРљ РІРєР»СЋС‡РёС‚СЃСЏ", "callback_data": "btn_notify_pc_online"}],
                [{"text": "рџЏ  Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ", "callback_data": "menu_main"}]
            ]
        }
        reply_or_edit(token, chat_id, message_obj, text, markup)
        return False
    return True

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

    # РџСЂРѕРІРµСЂРєР° РїСЂР°РІ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°
    if c_data.startswith("admin_"):
        if not is_admin(u_id, u_name):
            send_message(token, c_chat_id, "Р”РѕСЃС‚СѓРї Рє РїР°РЅРµР»Рё Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР° СЂР°Р·СЂРµС€РµРЅ С‚РѕР»СЊРєРѕ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ.")
            return

    # 1. Р“Р›РђР’РќРћР• РњР•РќР® Р РљРђРўР•Р“РћР РР
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

    # 2. РџР Р•РЎР•РўР« Р РЎР›РЈР§РђР™РќР«Р™ Р’Р«Р‘РћР 
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

    # 3. РќРђРЎРўР РћР™РљР (Р Р•Р–РРњ, Р РђР—Р Р•РЁР•РќРР• Р SAMPLES)
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
            val = max(15, min(30, val))
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
                "вљЎ <b>Р’Р’Р•Р”РРўР• РЁРђР“Р РЎР•РњРџР›РР РћР’РђРќРРЇ (SAMPLES)</b>\n\n"
                "РќР°РїРёС€РёС‚Рµ С‚РѕС‡РЅРѕРµ С‡РёСЃР»Рѕ С€Р°РіРѕРІ СЃРѕРѕР±С‰РµРЅРёРµРј РІ СЌС‚РѕС‚ С‡Р°С‚ (РѕС‚ 5 РґРѕ 60).\n"
                "Р РµРєРѕРјРµРЅРґСѓРµРјС‹Рµ Р·РЅР°С‡РµРЅРёСЏ: 15вЂ“30."
            )
        else:
            text = (
                "вљЎ <b>Р’Р’Р•Р”РРўР• РЁРђР“Р РЎР•РњРџР›РР РћР’РђРќРРЇ (SAMPLES)</b>\n\n"
                "РќР°РїРёС€РёС‚Рµ С‡РёСЃР»Рѕ С€Р°РіРѕРІ СЃРѕРѕР±С‰РµРЅРёРµРј РІ СЌС‚РѕС‚ С‡Р°С‚ (РѕС‚ 15 РґРѕ 30).\n"
                "Р РµРєРѕРјРµРЅРґСѓРµРјРѕРµ Р·РЅР°С‡РµРЅРёРµ РґР»СЏ С„РёСЂРјРµРЅРЅРѕРіРѕ СЃС‚РёР»СЏ: 28."
            )
        markup = {"inline_keyboard": [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "menu_samples"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "start_custom_res":
        c_sess["state"] = "awaiting_resolution"
        save_sessions()
        text = (
            "рџ“ђ <b>Р’Р’Р•Р”РРўР• Р РђР—Р Р•РЁР•РќРР• Р’ Р§РђРў</b>\n\n"
            "РќР°РїРёС€РёС‚Рµ Р¶РµР»Р°РµРјСѓСЋ С€РёСЂРёРЅСѓ Рё РІС‹СЃРѕС‚Сѓ РІ С„РѕСЂРјР°С‚Рµ РЁРР РРќРђxР’Р«РЎРћРўРђ (РЅР°РїСЂРёРјРµСЂ, 960x1280 РёР»Рё 1080x1080).\n\n"
            "РџСЂР°РІРёР»Р°:\n"
            "вЂў РЎС‚РѕСЂРѕРЅС‹ РЅРµ РґРѕР»Р¶РЅС‹ РїСЂРµРІС‹С€Р°С‚СЊ 1500 РїРёРєСЃРµР»РµР№\n"
            "вЂў РњРёРЅРёРјР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ: 512 РїРёРєСЃРµР»РµР№"
        )
        markup = {"inline_keyboard": [[{"text": "в—ЂпёЏ РќР°Р·Р°Рґ РІ РЅР°СЃС‚СЂРѕР№РєРё", "callback_data": "menu_settings"}]]}
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
            "рџЋЇ <b>Р’Р’Р•Р”РРўР• Р—РќРђР§Р•РќРР• CFG SCALE (РћРў 1 Р”Рћ 15)</b>\n\n"
            "РќР°РїРёС€РёС‚Рµ Р¶РµР»Р°РµРјСѓСЋ СЃРёР»Сѓ СЃРѕР±Р»СЋРґРµРЅРёСЏ РїСЂР°РІРёР» РїСЂРѕРјРїС‚Р° С‡РёСЃР»РѕРј РІ СЌС‚РѕС‚ С‡Р°С‚ (РЅР°РїСЂРёРјРµСЂ: <code>4.5</code>, <code>5.5</code>, <code>7.0</code>, <code>10</code> РёР»Рё <code>15</code>).\n\n"
            "вЂў Р”РѕРїСѓСЃС‚РёРјС‹Р№ РґРёР°РїР°Р·РѕРЅ: РѕС‚ <b>1.0</b> РґРѕ <b>15.0</b>\n"
            "вЂў РЎС‚Р°РЅРґР°СЂС‚РЅС‹Р№ Р±Р°Р»Р°РЅСЃ: <b>5.5</b>"
        )
        markup = {"inline_keyboard": [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "menu_cfg"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    # 4. Р¤РЈРќРљР¦РР РР
    elif c_data == "start_char_photo":
        c_sess["state"] = "awaiting_char_photo"
        save_sessions()
        text = (
            "рџ“ё <b>РџР•Р РЎРћРќРђР– РџРћ Р¤РћРўРћ</b>\n\n"
            "РћС‚РїСЂР°РІСЊС‚Рµ С„РѕС‚РѕРіСЂР°С„РёСЋ РёР»Рё Р°СЂС‚ РїРµСЂСЃРѕРЅР°Р¶Р° РїСЂСЏРјРѕ РІ СЌС‚РѕС‚ С‡Р°С‚.\n\n"
            "РР РїСЂРѕР°РЅР°Р»РёР·РёСЂСѓРµС‚ РёР·РѕР±СЂР°Р¶РµРЅРёРµ, "
            "РѕРїСЂРµРґРµР»РёС‚ РІРЅРµС€РЅРѕСЃС‚СЊ, РїСЂРёС‡РµСЃРєСѓ, С†РІРµС‚ РіР»Р°Р·, РѕРґРµР¶РґСѓ Рё СЃС„РѕСЂРјРёСЂСѓРµС‚ С‚РѕС‡РЅС‹Р№ РЅР°Р±РѕСЂ Danbooru-С‚РµРіРѕРІ "
            "РґР»СЏ СЃРѕР·РґР°РЅРёСЏ Р°СЂС‚Р° РІ РЅР°С€РµРј СЃС‚РёР»Рµ."
        )
        kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ", "callback_data": "menu_char"}]]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "start_ai_describe_char":
        c_sess["state"] = "awaiting_ai_char_name"
        save_sessions()
        cur_name = c_sess.get("char_name", "")
        text = (
            "вњЁ <b>Р РђРЎРџРћР—РќРђР’РђРќРР• РџР•Р РЎРћРќРђР–Рђ Р§Р•Р Р•Р— РР</b>\n\n"
            "Р•СЃР»Рё РЅРµР№СЂРѕСЃРµС‚СЊ РЅРµ Р·РЅР°РµС‚ РІР°С€РµРіРѕ РїРµСЂСЃРѕРЅР°Р¶Р° РёР»Рё СЂРёСЃСѓРµС‚ РµРіРѕ РЅРµС‚РѕС‡РЅРѕ, "
            "РР РЅР°Р№РґРµС‚ РґРµС‚Р°Р»Рё РІРЅРµС€РЅРѕСЃС‚Рё РїРµСЂСЃРѕРЅР°Р¶Р° Рё РїРµСЂРµРІРµРґРµС‚ РёС… РІ С‚РѕС‡РЅС‹Рµ Danbooru-С‚РµРіРё!\n\n"
            "РћС‚РїСЂР°РІСЊС‚Рµ РёРјСЏ РїРµСЂСЃРѕРЅР°Р¶Р° РЅР° Р°РЅРіР»РёР№СЃРєРѕРј СЃРѕРѕР±С‰РµРЅРёРµРј РІ С‡Р°С‚ "
            "(РЅР°РїСЂРёРјРµСЂ: <i>Jane Doe (Zenless Zone Zero), Makima, Yor Briar, 2B, Ahri, Loona</i>):"
        )
        kb = []
        if cur_name and cur_name != "РќРµ РІС‹Р±СЂР°РЅ":
            kb.append([{"text": f"вњЁ РћРїРёСЃР°С‚СЊ С‚РµРєСѓС‰РµРіРѕ: '{cur_name[:30]}'", "callback_data": "ai_describe_current"}])
        kb.append([{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ", "callback_data": "menu_char"}])
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "ai_describe_current":
        char_n = c_sess.get("char_name", "anime girl")
        reply_or_edit(token, c_chat_id, cb.get("message"), f"рџ”Ќ <i>РђРЅР°Р»РёР·РёСЂСѓСЋ РІРЅРµС€РЅРѕСЃС‚СЊ '{html.escape(char_n)}' С‡РµСЂРµР· РР... РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїРѕРґРѕР¶РґРёС‚Рµ (~5 СЃРµРє)...</i>")

        def _bg_describe():
            tags = describe_character_by_name(char_n)
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"вњ… <b>Р’РЅРµС€РЅРѕСЃС‚СЊ '{html.escape(char_n)}' СѓСЃРїРµС€РЅРѕ СЃС„РѕСЂРјРёСЂРѕРІР°РЅР° РР!</b>\n\n"
                f"<b>Danbooru-С‚РµРіРё РїРµСЂСЃРѕРЅР°Р¶Р°:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"РќР°Р¶РјРёС‚Рµ РєРЅРѕРїРєСѓ РЅРёР¶Рµ, С‡С‚РѕР±С‹ СЃРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ Р°СЂС‚:"
            )
            t_main, m_main = make_main_menu(c_sess, user_id=u_id, username=u_name)
            send_message(token, c_chat_id, res_text)
            send_message(token, c_chat_id, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_describe, daemon=True).start()

    elif c_data == "ai_describe_query_char":
        raw_query = c_sess.get("search_target", "custom character")
        reply_or_edit(token, c_chat_id, cb.get("message"), f"рџ”Ќ <i>РР РЅР°С…РѕРґРёС‚ С‚РѕС‡РЅС‹Рµ С‚РµРіРё РІРЅРµС€РЅРѕСЃС‚Рё РґР»СЏ '{html.escape(raw_query.title())}'... (~4-6 СЃРµРє)</i>")

        def _bg_query_describe():
            tags = describe_character_by_name(raw_query)
            c_sess["char_name"] = raw_query.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"вњ… <b>РџРµСЂСЃРѕРЅР°Р¶ '{html.escape(raw_query.title())}' СѓСЃРїРµС€РЅРѕ РѕР±СЂР°Р±РѕС‚Р°РЅ РР!</b>\n\n"
                f"<b>Danbooru-С‚РµРіРё:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"РўРµРіРё РїСЂРёРјРµРЅРµРЅС‹ Рє РІР°С€РµР№ СЃРµСЃСЃРёРё. РќР°Р¶РјРёС‚Рµ РєРЅРѕРїРєСѓ РЅРёР¶Рµ РґР»СЏ РіРµРЅРµСЂР°С†РёРё:"
            )
            t_main, m_main = make_main_menu(c_sess, user_id=u_id, username=u_name)
            send_message(token, c_chat_id, res_text)
            send_message(token, c_chat_id, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_query_describe, daemon=True).start()

    # 5. РћРќР›РђР™Рќ РџРћРРЎРљ
    elif c_data == "start_search_char":
        c_sess["state"] = "awaiting_char_query"
        save_sessions()
        text = (
            "рџ”Ќ <b>РћРќР›РђР™Рќ РџРћРРЎРљ РџР•Р РЎРћРќРђР–Рђ</b>\n\n"
            "РќР°РїРёС€РёС‚Рµ РёРјСЏ РїРµСЂСЃРѕРЅР°Р¶Р° РёР»Рё РЅР°Р·РІР°РЅРёРµ РёРіСЂС‹ РЅР° Р°РЅРіР»РёР№СЃРєРѕРј РІ С‡Р°С‚.\n"
            "РџСЂРёРјРµСЂС‹: <i>Jane Doe (Zenless Zone Zero), tifa, ahri, 2b, raven, loona, toriel, miku...</i>"
        )
        markup = {"inline_keyboard": [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ", "callback_data": "menu_char"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "start_search_pose":
        c_sess["state"] = "awaiting_pose_query"
        save_sessions()
        text = (
            "рџ”Ќ <b>РћРќР›РђР™Рќ РџРћРРЎРљ РџРћР—Р«</b>\n\n"
            "РќР°РїРёС€РёС‚Рµ РїРѕР·Сѓ РёР»Рё РґРµР№СЃС‚РІРёРµ РЅР° Р°РЅРіР»РёР№СЃРєРѕРј РІ С‡Р°С‚.\n"
            "РџСЂРёРјРµСЂС‹: sit, lying, all fours, kneeling, arch, back, standing, lean..."
        )
        markup = {"inline_keyboard": [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ", "callback_data": "menu_pose"}]]}
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "start_search_env":
        c_sess["state"] = "awaiting_env_query"
        save_sessions()
        text = (
            "рџ”Ќ <b>РћРќР›РђР™Рќ РџРћРРЎРљ РћРљР РЈР–Р•РќРРЇ</b>\n\n"
            "РќР°РїРёС€РёС‚Рµ С„РѕРЅ РёР»Рё Р»РѕРєР°С†РёСЋ РЅР° Р°РЅРіР»РёР№СЃРєРѕРј РІ С‡Р°С‚.\n"
            "РџСЂРёРјРµСЂС‹: ruins, bedroom, beach, forest, cyberpunk city, dungeon, bathhouse, classroom, throne room..."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "вќЊ Р‘РµР· РѕРєСЂСѓР¶РµРЅРёСЏ (РћС‡РёСЃС‚РёС‚СЊ)", "callback_data": "clear_env"}],
                [{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ", "callback_data": "menu_env"}]
            ]
        }
        reply_or_edit(token, c_chat_id, cb.get("message"), text, markup)

    elif c_data == "clear_env":
        c_sess["env_name"] = "Р‘РµР· РѕРєСЂСѓР¶РµРЅРёСЏ"
        c_sess["env_prompt"] = ""
        c_sess["state"] = "idle"
        save_sessions()
        t, m = make_env_menu(c_sess)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    # РџСЂРё РІС‹Р±РѕСЂРµ РїРµСЂСЃРѕРЅР°Р¶Р° Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё Р·Р°РїСЂР°С€РёРІР°РµРј С‚РѕС‡РЅРѕРµ РѕРїРёСЃР°РЅРёРµ РІРЅРµС€РЅРѕСЃС‚Рё Сѓ РР
    elif c_data.startswith("select_char_"):
        items = stored_searches.get(f"{c_chat_id}_char", [])
        try:
            idx = int(c_data.replace("select_char_", ""))
            if not items or idx < 0 or idx >= len(items):
                api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "вљ пёЏ Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Рё. РџРѕРІС‚РѕСЂРёС‚Рµ РїРѕРёСЃРє.", "show_alert": False})
                send_message(token, c_chat_id, "вљ пёЏ Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Рё. РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІС‹РїРѕР»РЅРёС‚Рµ РїРѕРёСЃРє Р·Р°РЅРѕРІРѕ.")
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
        reply_or_edit(token, c_chat_id, cb.get("message"), f"рџ”Ќ <i>РР РЅР°С…РѕРґРёС‚ С‚РѕС‡РЅС‹Рµ С‚РµРіРё РІРЅРµС€РЅРѕСЃС‚Рё РґР»СЏ '{html.escape(char_raw.title())}'... (~4-6 СЃРµРє)</i>")

        def _bg_select_ai():
            tags = describe_character_by_name(char_raw)
            c_sess["char_name"] = char_raw.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"вњ… <b>РџРµСЂСЃРѕРЅР°Р¶ '{html.escape(char_raw.title())}' РІС‹Р±СЂР°РЅ!</b>\n\n"
                f"<b>Danbooru-С‚РµРіРё РІРЅРµС€РЅРѕСЃС‚Рё (РР):</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"РўРµРїРµСЂСЊ РІС‹ РјРѕР¶РµС‚Рµ РЅР°Р¶Р°С‚СЊ <b>[рџљЂ РЎР“Р•РќР•Р РР РћР’РђРўР¬ РђР Рў]</b>."
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
                api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "вљ пёЏ Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Рё. РџРѕРІС‚РѕСЂРёС‚Рµ РїРѕРёСЃРє.", "show_alert": False})
                send_message(token, c_chat_id, "вљ пёЏ Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Рё. РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІС‹РїРѕР»РЅРёС‚Рµ РїРѕРёСЃРє Р·Р°РЅРѕРІРѕ.")
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
                api_call(token, "answerCallbackQuery", {"callback_query_id": cb_id, "text": "вљ пёЏ Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Рё. РџРѕРІС‚РѕСЂРёС‚Рµ РїРѕРёСЃРє.", "show_alert": False})
                send_message(token, c_chat_id, "вљ пёЏ Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Рё. РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІС‹РїРѕР»РЅРёС‚Рµ РїРѕРёСЃРє Р·Р°РЅРѕРІРѕ.")
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

    # РџСЂРёРјРµРЅРµРЅРёРµ РІРІРµРґРµРЅРЅРѕРіРѕ С‚РµРєСЃС‚Р° СЃ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРёРј СѓС‚РѕС‡РЅРµРЅРёРµРј РІРЅРµС€РЅРѕСЃС‚Рё С‡РµСЂРµР· РР
    elif c_data == "custom_char_apply":
        raw_query = c_sess.get("search_target", "custom character")
        reply_or_edit(token, c_chat_id, cb.get("message"), f"рџ”Ќ <i>РР РЅР°С…РѕРґРёС‚ С‚РѕС‡РЅС‹Рµ С‚РµРіРё РІРЅРµС€РЅРѕСЃС‚Рё РґР»СЏ '{html.escape(raw_query.title())}'... (~4-6 СЃРµРє)</i>")

        def _bg_apply_ai():
            tags = describe_character_by_name(raw_query)
            c_sess["char_name"] = raw_query.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"вњ… <b>РџРµСЂСЃРѕРЅР°Р¶ '{html.escape(raw_query.title())}' РІС‹Р±СЂР°РЅ!</b>\n\n"
                f"<b>Danbooru-С‚РµРіРё РІРЅРµС€РЅРѕСЃС‚Рё (РР):</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"РўРµРїРµСЂСЊ РІС‹ РјРѕР¶РµС‚Рµ РЅР°Р¶Р°С‚СЊ <b>[рџљЂ РЎР“Р•РќР•Р РР РћР’РђРўР¬ РђР Рў]</b>."
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

    # 6. РљРђРЎРўРћРњРќР«Р™ РџР РћРњРў Р РњРђР“РђР—РРќ STARS
    elif c_data == "menu_custom_prompt":
        c_sess["state"] = "awaiting_custom_prompt"
        save_sessions()
        text = (
            "вњЌпёЏ <b>Р Р•Р–РРњ РЎР’РћР•Р“Рћ РџР РћРњРўРђ</b>\n\n"
            "Р’ СЌС‚РѕРј СЂРµР¶РёРјРµ РІС‹ СЃР°РјРё Р·Р°РґР°РµС‚Рµ РІСЃРµ РґРµС‚Р°Р»Рё Р¶РµР»Р°РµРјРѕРіРѕ Р°СЂС‚Р°: РїРµСЂСЃРѕРЅР°Р¶Р°, РѕРґРµР¶РґСѓ РёР»Рё РµС‘ РѕС‚СЃСѓС‚СЃС‚РІРёРµ, СЂР°РєСѓСЂСЃ, РґРµР№СЃС‚РІРёРµ Рё РѕРєСЂСѓР¶РµРЅРёРµ.\n\n"
            "Р‘РѕС‚ РЅРµ РґРѕР±Р°РІР»СЏРµС‚ РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅС‹С… С‚РµРіРѕРІ РѕРґРµР¶РґС‹ РёР»Рё РЅР°РіРѕС‚С‹, Р° СЃРѕС…СЂР°РЅСЏРµС‚ С‚РѕР»СЊРєРѕ С„РёСЂРјРµРЅРЅС‹Р№ СЃС‚РёР»СЊ: <code>gummyflux, cstyle, &lt;lora:gummyflux:0.95&gt;</code>.\n\n"
            "РћС‚РїСЂР°РІСЊС‚Рµ РІР°С€ РїСЂРѕРјС‚ РЅР° СЂСѓСЃСЃРєРѕРј РёР»Рё Р°РЅРіР»РёР№СЃРєРѕРј СЏР·С‹РєРµ СЃРѕРѕР±С‰РµРЅРёРµРј РїСЂСЏРјРѕ РІ С‡Р°С‚:"
        )
        kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ РІ РјРµРЅСЋ", "callback_data": "menu_main"}]]
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
                "title": f"РџР°РєРµС‚: {pkg['title']}",
                "description": f"РџРѕРєСѓРїРєР° {pkg['count']} РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹С… РіРµРЅРµСЂР°С†РёР№ Р°СЂС‚РѕРІ РІ GummyFlux Р±РµР· РѕРіСЂР°РЅРёС‡РµРЅРёР№ РїРѕ РІСЂРµРјРµРЅРё.",
                "payload": f"stars_pkg_{pkg_key}_{u_id}_{int(time.time())}",
                "provider_token": "",
                "currency": "XTR",
                "prices": json.dumps([{"label": f"{pkg['count']} РіРµРЅ.", "amount": pkg['stars']}])
            }
            api_call(token, "sendInvoice", invoice_payload)

    elif c_data == "btn_notify_pc_online":
        if is_backend_online():
            api_call(token, "answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": "вљЎ РџРљ СѓР¶Рµ РІРєР»СЋС‡РµРЅ! Р’С‹ РјРѕР¶РµС‚Рµ РіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ.",
                "show_alert": False
            })
            reply_or_edit(
                token, c_chat_id, cb.get("message"),
                "вљЎ <b>РљРѕРјРїСЊСЋС‚РµСЂ РІРєР»СЋС‡РµРЅ Рё РіРѕС‚РѕРІ Рє СЂР°Р±РѕС‚Рµ!</b>\n\nР’С‹ РјРѕР¶РµС‚Рµ РїРµСЂРµР№С‚Рё РІ РіР»Р°РІРЅРѕРµ РјРµРЅСЋ Рё РЅР°С‡Р°С‚СЊ РіРµРЅРµСЂР°С†РёСЋ.",
                reply_markup={"inline_keyboard": [[{"text": "рџЋЁ РЎРѕР·РґР°С‚СЊ Р°СЂС‚", "callback_data": "menu_main"}]]}
            )
        else:
            add_pc_notify(c_chat_id)
            api_call(token, "answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": "рџ”” Р’С‹ РґРѕР±Р°РІР»РµРЅС‹ РІ СЃРїРёСЃРѕРє СѓРІРµРґРѕРјР»РµРЅРёР№!",
                "show_alert": False
            })
            reply_or_edit(
                token, c_chat_id, cb.get("message"),
                "рџ”” <b>Р’С‹ РїРѕРґРїРёСЃР°Р»РёСЃСЊ РЅР° СѓРІРµРґРѕРјР»РµРЅРёРµ!</b>\n\n"
                "РљР°Рє С‚РѕР»СЊРєРѕ РєРѕРјРїСЊСЋС‚РµСЂ РІРєР»СЋС‡РёС‚СЃСЏ Рё СЃР»СѓР¶Р±Р° РЅРµР№СЂРѕСЃРµС‚Рё Р·Р°РїСѓСЃС‚РёС‚СЃСЏ, Р±РѕС‚ СЃСЂР°Р·Сѓ РїСЂРёС€Р»РµС‚ РІР°Рј СЃРѕРѕР±С‰РµРЅРёРµ.",
                reply_markup={"inline_keyboard": [[{"text": "рџЏ  Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ", "callback_data": "menu_main"}]]}
            )

    # 7. Р“Р•РќР•Р РђР¦РРЇ РђР РўРђ (РЎ РћР‘РЇР—РђРўР•Р›Р¬РќР«Рњ РџРћР”РўР’Р•Р Р–Р”Р•РќРР•Рњ)
    elif c_data == "action_generate":
        if not check_pc_online_or_notify(token, c_chat_id, cb.get("message")):
            return
        t, m = make_confirm_generation_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

    elif c_data == "confirm_exec_generate":
        if not check_pc_online_or_notify(token, c_chat_id, cb.get("message")):
            return
        with active_lock:
            if u_id in active_generations:
                send_message(token, c_chat_id, "Р’Р°С€ Р·Р°РїСЂРѕСЃ СѓР¶Рµ РЅР°С…РѕРґРёС‚СЃСЏ РІ СЂР°Р±РѕС‚Рµ РёР»Рё РІ РѕС‡РµСЂРµРґРё.")
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(token, c_chat_id, f"Р”РѕСЃС‚РёРіРЅСѓС‚ РґРЅРµРІРЅРѕР№ Р»РёРјРёС‚ РіРµРЅРµСЂР°С†РёР№ (РѕСЃС‚Р°Р»РѕСЃСЊ {f_left} РёР· {u_base}, Р±РѕРЅСѓСЃРЅС‹С…: {b_left}). Р’С‹ РјРѕР¶РµС‚Рµ РїСЂРёРѕР±СЂРµСЃС‚Рё РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅСѓСЋ РіРµРЅРµСЂР°С†РёСЋ СЃРѕ СЃРєРёРґРєРѕР№ РїРѕ РєРЅРѕРїРєРµ РІ РјРµРЅСЋ РёР»Рё РґРѕР¶РґР°С‚СЊСЃСЏ РїРѕР»СѓРЅРѕС‡Рё.")
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
            reply_or_edit(token, c_chat_id, cb.get("message"), f"вЏі <b>Р—Р°РїСЂРѕСЃ РїРѕРґС‚РІРµСЂР¶РґРµРЅ Рё РґРѕР±Р°РІР»РµРЅ РІ РѕС‡РµСЂРµРґСЊ!</b>\nРџРѕР·РёС†РёСЏ РІ РѕС‡РµСЂРµРґРё: {q_pos}")

            steps = int(c_sess.get("steps", 20))
            if not is_admin(u_id, u_name):
                steps = max(15, min(25, steps))
            model = c_sess.get("model", DEFAULT_MODEL)

            c_sess["last_is_custom"] = False
            save_sessions()
            from bot.queue_helper import put_task
            put_task(generation_queue, u_id, is_admin(u_id, u_name), {
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
                "char_name": c_sess.get('char_name', 'РџРµСЂСЃРѕРЅР°Р¶'),
                "pose_name": c_sess.get('pose_name', 'РџРѕР·Р°'),
                "env_name": c_sess.get('env_name', 'РћРєСЂСѓР¶РµРЅРёРµ'),
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
            send_message(token, c_chat_id, f"РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РїРѕСЃС‚Р°РЅРѕРІРєРµ Р·Р°РґР°С‡Рё РІ РѕС‡РµСЂРµРґСЊ: {e}")

    elif c_data == "confirm_exec_custom":
        if not check_pc_online_or_notify(token, c_chat_id, cb.get("message")):
            return
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "РџСЂРѕРјС‚ РЅРµ РЅР°Р№РґРµРЅ РёР»Рё Р±С‹Р» РѕС‚РјРµРЅРµРЅ.", reply_markup={"inline_keyboard": [[{"text": "в—ЂпёЏ Р’ РіР»Р°РІРЅРѕРµ РјРµРЅСЋ", "callback_data": "menu_main"}]]})
            return

        with active_lock:
            if u_id in active_generations:
                send_message(token, c_chat_id, "Р’Р°С€ Р·Р°РїСЂРѕСЃ СѓР¶Рµ РЅР°С…РѕРґРёС‚СЃСЏ РІ СЂР°Р±РѕС‚Рµ РёР»Рё РІ РѕС‡РµСЂРµРґРё.")
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(token, c_chat_id, f"Р”РѕСЃС‚РёРіРЅСѓС‚ РґРЅРµРІРЅРѕР№ Р»РёРјРёС‚ РіРµРЅРµСЂР°С†РёР№ (РѕСЃС‚Р°Р»РѕСЃСЊ {f_left} РёР· {u_base}, Р±РѕРЅСѓСЃРЅС‹С…: {b_left}). Р’С‹ РјРѕР¶РµС‚Рµ РїСЂРёРѕР±СЂРµСЃС‚Рё РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅСѓСЋ РіРµРЅРµСЂР°С†РёСЋ СЃРѕ СЃРєРёРґРєРѕР№ РїРѕ РєРЅРѕРїРєРµ РІ РјРµРЅСЋ РёР»Рё РґРѕР¶РґР°С‚СЊСЃСЏ РїРѕР»СѓРЅРѕС‡Рё.")
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
            reply_or_edit(token, c_chat_id, cb.get("message"), f"вЏі <b>РљР°СЃС‚РѕРјРЅС‹Р№ Р·Р°РїСЂРѕСЃ РїРѕРґС‚РІРµСЂР¶РґРµРЅ Рё РїСЂРёРЅСЏС‚ РІ РѕС‡РµСЂРµРґСЊ!</b>\nРџРѕР·РёС†РёСЏ РІ РѕС‡РµСЂРµРґРё: {q_pos}")

            c_sess["last_is_custom"] = True
            c_sess["last_custom_prompt"] = raw_prompt
            save_sessions()

            from bot.queue_helper import put_task
            put_task(generation_queue, u_id, is_admin(u_id, u_name), {
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
                "char_name": "РљР°СЃС‚РѕРјРЅС‹Р№ Р°СЂС‚",
                "pose_name": "РЎРІРѕСЏ РїРѕР·Р°",
                "env_name": "РЎРІРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ",
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
            send_message(token, c_chat_id, f"РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РїРѕСЃС‚Р°РЅРѕРІРєРµ Р·Р°РґР°С‡Рё РІ РѕС‡РµСЂРµРґСЊ: {e}")

    elif c_data == "confirm_exec_custom_ai":
        if not check_pc_online_or_notify(token, c_chat_id, cb.get("message")):
            return
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "РџСЂРѕРјС‚ РЅРµ РЅР°Р№РґРµРЅ РёР»Рё Р±С‹Р» РѕС‚РјРµРЅРµРЅ.", reply_markup={"inline_keyboard": [[{"text": "в—ЂпёЏ Р’ РіР»Р°РІРЅРѕРµ РјРµРЅСЋ", "callback_data": "menu_main"}]]})
            return

        with active_lock:
            if u_id in active_generations:
                send_message(token, c_chat_id, "Р’Р°С€ Р·Р°РїСЂРѕСЃ СѓР¶Рµ РЅР°С…РѕРґРёС‚СЃСЏ РІ СЂР°Р±РѕС‚Рµ РёР»Рё РІ РѕС‡РµСЂРµРґРё.")
                return

            allowed, reason, consumed_type = consume_user_generation(u_id, u_name)
            if not allowed:
                db = load_db()
                u_base = db.get("users", {}).get(str(u_id), {}).get("base_daily_limit", 3)
                _, f_left, b_left, _ = get_user_limits_status(u_id, u_name)
                send_message(token, c_chat_id, f"Р”РѕСЃС‚РёРіРЅСѓС‚ РґРЅРµРІРЅРѕР№ Р»РёРјРёС‚ РіРµРЅРµСЂР°С†РёР№ (РѕСЃС‚Р°Р»РѕСЃСЊ {f_left} РёР· {u_base}, Р±РѕРЅСѓСЃРЅС‹С…: {b_left}). Р’С‹ РјРѕР¶РµС‚Рµ РїСЂРёРѕР±СЂРµСЃС‚Рё РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅСѓСЋ РіРµРЅРµСЂР°С†РёСЋ СЃРѕ СЃРєРёРґРєРѕР№ РїРѕ РєРЅРѕРїРєРµ РІ РјРµРЅСЋ РёР»Рё РґРѕР¶РґР°С‚СЊСЃСЏ РїРѕР»СѓРЅРѕС‡Рё.")
                return

            active_generations.add(u_id)

        reply_or_edit(token, c_chat_id, cb.get("message"), f"вњЁ <i>РР РґРµС‚Р°Р»СЊРЅРѕ РїСЂРѕСЂР°Р±Р°С‚С‹РІР°РµС‚ Рё РѕР±РѕРіР°С‰Р°РµС‚ РїСЂРѕРјС‚ РґР»СЏ '{html.escape(raw_prompt[:60])}' (~3-5 СЃРµРє)...</i>")

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
                    f"вЏі <b>Р—Р°РїСЂРѕСЃ РґРµС‚Р°Р»СЊРЅРѕ СЃРѕСЃС‚Р°РІР»РµРЅ С‡РµСЂРµР· РР Рё РїСЂРёРЅСЏС‚ РІ РѕС‡РµСЂРµРґСЊ!</b>\nРџРѕР·РёС†РёСЏ: {q_pos}\n\n"
                    f"<b>Danbooru-РїСЂРѕРјС‚ РР:</b>\n<code>{html.escape(enhanced_tags[:200])}...</code>\n\n"
                    f"рџЋЁ <b>Р¤РёСЂРјРµРЅРЅС‹Р№ СЃС‚РёР»СЊ:</b> <code>gummyflux, cstyle, &lt;lora:gummyflux:0.95&gt;</code>"
                )

                from bot.queue_helper import put_task
            put_task(generation_queue, u_id, is_admin(u_id, u_name), {
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
                    "char_name": "РљР°СЃС‚РѕРјРЅС‹Р№ Р°СЂС‚ (РР)",
                    "pose_name": "РЎРІРѕСЏ РїРѕР·Р°",
                    "env_name": "РЎРІРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ",
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
                send_message(token, c_chat_id, f"РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РѕР±СЂР°Р±РѕС‚РєРµ Р·Р°РїСЂРѕСЃР° РР: {e}")

        threading.Thread(target=_bg_exec_ai_custom, daemon=True).start()

    elif c_data == "quick_rerun":
        if not check_pc_online_or_notify(token, c_chat_id, cb.get("message")):
            return
        with active_lock:
            if u_id in active_generations:
                api_call(token, "answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "вЏі Р’Р°С€Р° РїСЂРµРґС‹РґСѓС‰Р°СЏ РіРµРЅРµСЂР°С†РёСЏ РµС‰Рµ РІ РїСЂРѕС†РµСЃСЃРµ!",
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
                    f"Р”РѕСЃС‚РёРіРЅСѓС‚ РґРЅРµРІРЅРѕР№ Р»РёРјРёС‚ РіРµРЅРµСЂР°С†РёР№ (РѕСЃС‚Р°Р»РѕСЃСЊ {f_left} РёР· {u_base}, Р±РѕРЅСѓСЃРЅС‹С…: {b_left}). "
                    "Р’С‹ РјРѕР¶РµС‚Рµ РїСЂРёРѕР±СЂРµСЃС‚Рё РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ РіРµРЅРµСЂР°С†РёРё РїРѕ РєРЅРѕРїРєРµ РІ РјРµРЅСЋ РёР»Рё РґРѕР¶РґР°С‚СЊСЃСЏ РїРѕР»СѓРЅРѕС‡Рё."
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
                char_name = "РљР°СЃС‚РѕРјРЅС‹Р№ Р°СЂС‚"
                pose_name = "РЎРІРѕСЏ РїРѕР·Р°"
                env_name = "РЎРІРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ"
                send_message(token, c_chat_id, f"вЏі <b>РџРѕРІС‚РѕСЂРЅР°СЏ РіРµРЅРµСЂР°С†РёСЏ РєР°СЃС‚РѕРјРЅРѕРіРѕ Р°СЂС‚Р° РїСЂРёРЅСЏС‚Р° РІ РѕС‡РµСЂРµРґСЊ!</b>\nРџРѕР·РёС†РёСЏ: {q_pos}")
            else:
                prompt_parts = [c_sess.get("char_prompt", "1girl, solo"), c_sess.get("pose_prompt", "looking at viewer")]
                if c_sess.get("env_prompt"):
                    prompt_parts.append(c_sess["env_prompt"])
                prompt = ", ".join(p for p in prompt_parts if p)
                char_name = c_sess.get('char_name', 'РџРµСЂСЃРѕРЅР°Р¶')
                pose_name = c_sess.get('pose_name', 'РџРѕР·Р°')
                env_name = c_sess.get('env_name', 'РћРєСЂСѓР¶РµРЅРёРµ')
                send_message(token, c_chat_id, f"вЏі <b>РќРѕРІС‹Р№ РІР°СЂРёР°РЅС‚ {html.escape(char_name)} РїСЂРёРЅСЏС‚ РІ РѕС‡РµСЂРµРґСЊ!</b>\nРџРѕР·РёС†РёСЏ: {q_pos}")

            from bot.queue_helper import put_task
            put_task(generation_queue, u_id, is_admin(u_id, u_name), {
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
            send_message(token, c_chat_id, f"РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РїРѕСЃС‚Р°РЅРѕРІРєРµ Р·Р°РґР°С‡Рё РІ РѕС‡РµСЂРµРґСЊ: {e}")

    elif c_data == "quick_toggle_mode":
        if not check_pc_online_or_notify(token, c_chat_id, cb.get("message")):
            return
        with active_lock:
            if u_id in active_generations:
                api_call(token, "answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "вЏі Р’Р°С€Р° РїСЂРµРґС‹РґСѓС‰Р°СЏ РіРµРЅРµСЂР°С†РёСЏ РµС‰Рµ РІ РїСЂРѕС†РµСЃСЃРµ!",
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
                    f"Р”РѕСЃС‚РёРіРЅСѓС‚ РґРЅРµРІРЅРѕР№ Р»РёРјРёС‚ РіРµРЅРµСЂР°С†РёР№ (РѕСЃС‚Р°Р»РѕСЃСЊ {f_left} РёР· {u_base}, Р±РѕРЅСѓСЃРЅС‹С…: {b_left}). "
                    "Р’С‹ РјРѕР¶РµС‚Рµ РїСЂРёРѕР±СЂРµСЃС‚Рё РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ РіРµРЅРµСЂР°С†РёРё РїРѕ РєРЅРѕРїРєРµ РІ РјРµРЅСЋ РёР»Рё РґРѕР¶РґР°С‚СЊСЃСЏ РїРѕР»СѓРЅРѕС‡Рё."
                )
                return

            active_generations.add(u_id)

        try:
            new_mode = "sfw" if c_sess.get("mode") == "nsfw" else "nsfw"
            c_sess["mode"] = new_mode
            save_sessions()
            is_nsfw = (new_mode == "nsfw")
            mode_label = "рџ”Ґ Р‘РµР· РѕРґРµР¶РґС‹ (NSFW)" if is_nsfw else "рџ‘— Р’ РѕРґРµР¶РґРµ (SFW)"

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
                char_name = "РљР°СЃС‚РѕРјРЅС‹Р№ Р°СЂС‚"
                pose_name = "РЎРІРѕСЏ РїРѕР·Р°"
                env_name = "РЎРІРѕРµ РѕРєСЂСѓР¶РµРЅРёРµ"
                send_message(token, c_chat_id, f"вЏі <b>Р РµР¶РёРј РїРµСЂРµРєР»СЋС‡РµРЅ: {mode_label}!</b>\nРљР°СЃС‚РѕРјРЅС‹Р№ Р°СЂС‚ РїСЂРёРЅСЏС‚ РІ РѕС‡РµСЂРµРґСЊ (РїРѕР·РёС†РёСЏ: {q_pos})...")
            else:
                prompt_parts = [c_sess.get("char_prompt", "1girl, solo"), c_sess.get("pose_prompt", "looking at viewer")]
                if c_sess.get("env_prompt"):
                    prompt_parts.append(c_sess["env_prompt"])
                prompt = ", ".join(p for p in prompt_parts if p)
                char_name = c_sess.get('char_name', 'РџРµСЂСЃРѕРЅР°Р¶')
                pose_name = c_sess.get('pose_name', 'РџРѕР·Р°')
                env_name = c_sess.get('env_name', 'РћРєСЂСѓР¶РµРЅРёРµ')
                send_message(token, c_chat_id, f"вЏі <b>Р РµР¶РёРј РїРµСЂРµРєР»СЋС‡РµРЅ: {mode_label}!</b>\nР“РµРЅРµСЂР°С†РёСЏ {html.escape(char_name)} РїСЂРёРЅСЏС‚Р° РІ РѕС‡РµСЂРµРґСЊ (РїРѕР·РёС†РёСЏ: {q_pos})...")

            from bot.queue_helper import put_task
            put_task(generation_queue, u_id, is_admin(u_id, u_name), {
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
            send_message(token, c_chat_id, f"РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РїРѕСЃС‚Р°РЅРѕРІРєРµ Р·Р°РґР°С‡Рё РІ РѕС‡РµСЂРµРґСЊ: {e}")

    elif c_data == "custom_search_char":
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "Р—Р°РїСЂРѕСЃ РЅРµ РЅР°Р№РґРµРЅ.", reply_markup={"inline_keyboard": [[{"text": "в—ЂпёЏ Р’ РјРµРЅСЋ", "callback_data": "menu_main"}]]})
            return
        reply_or_edit(token, c_chat_id, cb.get("message"), f"рџ”Ќ <i>РћРїСЂРµРґРµР»СЏСЋ РїРµСЂСЃРѕРЅР°Р¶Р° '{html.escape(raw_prompt)}'...</i>")
        def _bg_char_from_prompt():
            tags = describe_character_by_name(raw_prompt)
            c_sess["char_name"] = raw_prompt.title()
            c_sess["char_prompt"] = tags
            c_sess["state"] = "idle"
            save_sessions()
            t, m = make_char_menu(c_sess)
            send_message(token, c_chat_id, f"вњ… РџРµСЂСЃРѕРЅР°Р¶ <b>{html.escape(raw_prompt.title())}</b> СѓСЃРїРµС€РЅРѕ СѓСЃС‚Р°РЅРѕРІР»РµРЅ!\n\nРўРµРіРё: <code>{html.escape(tags)}</code>")
            send_message(token, c_chat_id, t, reply_markup=m)
        threading.Thread(target=_bg_char_from_prompt, daemon=True).start()

    elif c_data == "custom_enhance_ai":
        raw_prompt = c_sess.get("pending_custom_prompt", "")
        if not raw_prompt:
            reply_or_edit(token, c_chat_id, cb.get("message"), "Р—Р°РїСЂРѕСЃ РЅРµ РЅР°Р№РґРµРЅ.", reply_markup={"inline_keyboard": [[{"text": "в—ЂпёЏ Р’ РјРµРЅСЋ", "callback_data": "menu_main"}]]})
            return
        reply_or_edit(token, c_chat_id, cb.get("message"), "вњЁ <i>РР РґРµС‚Р°Р»СЊРЅРѕ РїСЂРѕСЂР°Р±Р°С‚С‹РІР°РµС‚ Рё СЂР°СЃС€РёСЂСЏРµС‚ РїСЂРѕРјС‚... (~3-5 СЃРµРє)...</i>")

        def _bg_enhance():
            enhanced = enhance_prompt_with_ai(raw_prompt)
            c_sess["pending_custom_prompt"] = enhanced
            save_sessions()
            t_conf, m_conf = make_confirm_custom_menu(enhanced, c_sess, user_id=u_id, username=u_name)
            send_message(
                token, c_chat_id,
                f"вњ… <b>РџСЂРѕРјС‚ РґРµС‚Р°Р»РёР·РёСЂРѕРІР°РЅ РР!</b>\n\n"
                f"<b>РџРѕРґСЂРѕР±РЅС‹Р№ РЅР°Р±РѕСЂ С‚РµРіРѕРІ:</b>\n<code>{html.escape(enhanced)}</code>"
            )
            send_message(token, c_chat_id, t_conf, reply_markup=m_conf)

        threading.Thread(target=_bg_enhance, daemon=True).start()

    elif c_data == "cancel_custom_prompt":
        c_sess["pending_custom_prompt"] = ""
        c_sess["state"] = "idle"
        t, m = make_main_menu(c_sess, user_id=u_id, username=u_name)
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)


    # 8. РџРђРќР•Р›Р¬ РђР”РњРРќРРЎРўР РђРўРћР Рђ
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
            "рџ”Ќ <b>РџРћРРЎРљ РџРћР›Р¬Р—РћР’РђРўР•Р›РЇ</b>\n\n"
            "РћС‚РїСЂР°РІСЊС‚Рµ РІ С‡Р°С‚ @username, С‡РёСЃР»РѕРІРѕР№ Telegram ID РёР»Рё РёРјСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ:"
        )
        kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "admin_users_page_0"}]]
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
            f"вњЏпёЏ <b>Р’Р’Р•Р”РРўР• Р‘РђР—РћР’Р«Р™ Р›РРњРРў Р’ Р§РђРў</b>\n\n"
            f"Р”Р»СЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ ID {html.escape(target_uid)}.\n"
            "РќР°РїРёС€РёС‚Рµ С‡РёСЃР»Рѕ Р±РµСЃРїР»Р°С‚РЅС‹С… РіРµРЅРµСЂР°С†РёР№ РІ РґРµРЅСЊ (РЅР°РїСЂРёРјРµСЂ, 5, 10 РёР»Рё 50):"
        )
        kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": f"admin_user_{target_uid}"}]]
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
                send_message(token, target_uid, f"рџЋЃ РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ РЅР°С‡РёСЃР»РёР» РІР°Рј +{amount_val} РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹С… РіРµРЅРµСЂР°С†РёР№ Р°СЂС‚РѕРІ! РџСЂРёСЏС‚РЅРѕРіРѕ С‚РІРѕСЂС‡РµСЃС‚РІР°!")
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
            f"рџЋЃ <b>Р’Р’Р•Р”РРўР• РљРћР›РР§Р•РЎРўР’Рћ Р“Р•РќР•Р РђР¦РР™ Р’ Р§РђРў</b>\n\n"
            f"Р”Р»СЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ ID {html.escape(target_uid)}.\n"
            "РќР°РїРёС€РёС‚Рµ С‡РёСЃР»Рѕ Р±РѕРЅСѓСЃРЅС‹С… РіРµРЅРµСЂР°С†РёР№ РґР»СЏ РЅР°С‡РёСЃР»РµРЅРёСЏ (РЅР°РїСЂРёРјРµСЂ, 10 РёР»Рё 25):"
        )
        kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": f"admin_user_{target_uid}"}]]
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
                            f"рџ–ј РђСЂС‚ [{h.get('id', '')}]\n"
                            f"рџ‘¤ РђРІС‚РѕСЂ: {html.escape(str(uname))} (ID: {h.get('user_id')})\n"
                            f"рџ•’ Р’СЂРµРјСЏ: {html.escape(str(h.get('time', '')))}\n"
                            f"вљ™пёЏ РџР°СЂР°РјРµС‚СЂС‹: {mode_txt}, {h.get('res')}, {h.get('elapsed')} СЃРµРє.\n"
                            f"рџ“ќ РџСЂРѕРјС‚: {html.escape(str(h.get('prompt', ''))[:400])}"
                        )
                        kb = [[{"text": "в—ЂпёЏ РќР°Р·Р°Рґ Рє РёСЃС‚РѕСЂРёРё", "callback_data": "admin_hist_page_0"}]]
                        send_photo(token, c_chat_id, img_bytes, caption=caption, reply_markup={"inline_keyboard": kb})
                        found = True
                        break
                    except Exception as e:
                        send_message(token, c_chat_id, f"РћС€РёР±РєР° С‡С‚РµРЅРёСЏ С„Р°Р№Р»Р°: {e}")
                        found = True
                        break
        if not found:
            send_message(token, c_chat_id, "Р¤Р°Р№Р» РёР·РѕР±СЂР°Р¶РµРЅРёСЏ РЅРµ РЅР°Р№РґРµРЅ РЅР° РґРёСЃРєРµ (РіРµРЅРµСЂР°С†РёСЏ Р±С‹Р»Р° РґРѕ РІРєР»СЋС‡РµРЅРёСЏ Р°СЂС…РёРІР°С†РёРё).")

    elif c_data == "admin_confirm_reset_all_view":
        db = load_db()
        total_u = len(db.get("users", {}))
        text = (
            "вљ пёЏ <b>РњРђРЎРЎРћР’Р«Р™ РЎР‘Р РћРЎ Р›РРњРРўРћР’ Р’РЎР•Рњ РџРћР›Р¬Р—РћР’РђРўР•Р›РЇРњ</b>\n\n"
            f"Р’С‹ СЃРѕР±РёСЂР°РµС‚РµСЃСЊ РѕР±РЅСѓР»РёС‚СЊ СЃСѓС‚РѕС‡РЅС‹Р№ СЃС‡РµС‚С‡РёРє РіРµРЅРµСЂР°С†РёР№ РґР»СЏ РІСЃРµС… РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ Р±РѕС‚Р° (РІСЃРµРіРѕ РІ Р±Р°Р·Рµ: {total_u}).\n\n"
            "РљР°Р¶РґРѕРјСѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ Р±СѓРґРµС‚ РѕС‚РїСЂР°РІР»РµРЅРѕ РїРµСЂСЃРѕРЅР°Р»СЊРЅРѕРµ СѓРІРµРґРѕРјР»РµРЅРёРµ РІ С‡Р°С‚ СЃ Р±РѕС‚РѕРј Рѕ С‚РѕРј, С‡С‚Рѕ РµРіРѕ СЃСѓС‚РѕС‡РЅС‹Р№ Р»РёРјРёС‚ СЃРЅРѕРІР° РїРѕР»РѕРЅ.\n\n"
            "РџРѕРґС‚РІРµСЂРґРёС‚СЊ СЃР±СЂРѕСЃ?"
        )
        kb = [
            [{"text": "вњ… Р”Р°, СЃР±СЂРѕСЃРёС‚СЊ РІСЃРµРј Рё СЂР°Р·РѕСЃР»Р°С‚СЊ", "callback_data": "admin_do_reset_all"}],
            [{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ", "callback_data": "admin_users_page_0"}]
        ]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "admin_do_reset_all":
        reply_or_edit(token, c_chat_id, cb.get("message"), "вЏі <b>Р’С‹РїРѕР»РЅСЏРµС‚СЃСЏ СЃР±СЂРѕСЃ Р»РёРјРёС‚РѕРІ Рё СЂР°СЃСЃС‹Р»РєР° СѓРІРµРґРѕРјР»РµРЅРёР№...</b>\nРџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїРѕРґРѕР¶РґРёС‚Рµ Р·Р°РІРµСЂС€РµРЅРёСЏ РѕРїРµСЂР°С†РёРё.")
        reset_all_users_daily_limits_async(token, c_chat_id, send_message)

    elif c_data == "admin_safe_restart":
        perform_safe_reload(token, c_chat_id)

    elif c_data == "admin_confirm_shutdown":
        text = (
            "вљ пёЏ <b>Р’Р«РљР›Р®Р§Р•РќРР• Р‘РћРўРђ</b>\n\n"
            "Р’С‹ РґРµР№СЃС‚РІРёС‚РµР»СЊРЅРѕ С…РѕС‚РёС‚Рµ РїРѕР»РЅРѕСЃС‚СЊСЋ РѕС‚РєР»СЋС‡РёС‚СЊ Telegram Р±РѕС‚Р°?\n\n"
            "РџРѕСЃР»Рµ РІС‹РєР»СЋС‡РµРЅРёСЏ СЃРµСЂРІРёСЃ РїРµСЂРµСЃС‚Р°РЅРµС‚ РѕС‚РІРµС‡Р°С‚СЊ РЅР° СЃРѕРѕР±С‰РµРЅРёСЏ Рё РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊ Р·Р°РїСЂРѕСЃС‹, "
            "РїРѕРєР° РµРіРѕ РЅРµ Р·Р°РїСѓСЃС‚СЏС‚ Р·Р°РЅРѕРІРѕ РЅР° РєРѕРјРїСЊСЋС‚РµСЂРµ.\n\n"
            "РџРѕРґС‚РІРµСЂРґРёС‚СЊ РІС‹РєР»СЋС‡РµРЅРёРµ?"
        )
        kb = [
            [{"text": "рџ›‘ Р”Р°, РїРѕР»РЅРѕСЃС‚СЊСЋ РІС‹РєР»СЋС‡РёС‚СЊ Р±РѕС‚Р°", "callback_data": "admin_do_shutdown"}],
            [{"text": "в—ЂпёЏ РћС‚РјРµРЅР° / РќР°Р·Р°Рґ", "callback_data": "admin_main"}]
        ]
        reply_or_edit(token, c_chat_id, cb.get("message"), text, {"inline_keyboard": kb})

    elif c_data == "admin_do_shutdown":
        reply_or_edit(token, c_chat_id, cb.get("message"), "рџ›‘ <b>РРЅРёС†РёРёСЂРѕРІР°РЅ РїСЂРѕС†РµСЃСЃ РІС‹РєР»СЋС‡РµРЅРёСЏ Р±РѕС‚Р°...</b>")
        perform_safe_shutdown(token, c_chat_id, reason="РљРѕРјР°РЅРґР° РёР· Р°РґРјРёРЅ-РїР°РЅРµР»Рё Telegram")

    elif c_data == "admin_messages":
        t, m = render_admin_messages()
        reply_or_edit(token, c_chat_id, cb.get("message"), t, m)

def handle_message(token, msg, stored_searches):
    m_chat = str(msg['chat']['id'])
    m_sess = get_session(m_chat)
    if "photo" in msg:
        photos = msg["photo"]
        best_photo = max(photos, key=lambda p: p.get("file_size", 0))
        file_id = best_photo["file_id"]
        
        from bot.telegram_api import get_file, download_file
        import base64
        file_path = get_file(token, file_id)
        if file_path:
            img_bytes = download_file(token, file_path)
            if img_bytes:
                b64 = base64.b64encode(img_bytes).decode('utf-8')
                m_sess["init_image_b64"] = f"data:image/jpeg;base64,{b64}"
                from bot.config import save_sessions
                save_sessions()
                
                send_message(token, m_chat, "✅ <b>Фотография сохранена!</b>\n\nНажмите кнопку ниже, чтобы применить текущие настройки (персонаж, стиль, окружение) к вашему фото (Image-to-Image).", reply_markup={
                    "inline_keyboard": [
                        [{"text": "✨ Сгенерировать Image-to-Image", "callback_data": "generate_img2img"}]
                    ]
                })
        return
    m_chat = str(msg["chat"]["id"])
    msg_user = msg.get("from", {})
    u_id = str(msg_user.get("id", m_chat))
    u_name = msg_user.get("username", "")
    u_fname = msg_user.get("first_name", "")

    touch_user(u_id, u_name, u_fname)
    m_sess = get_session(m_chat)

    # 1. РћР‘Р РђР‘РћРўРљРђ РћРџР›РђРўР« TELEGRAM STARS
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
            send_message(token, m_chat, f"рџЋ‰ <b>РћРїР»Р°С‚Р° {amount_stars} в­ђпёЏ Stars СѓСЃРїРµС€РЅРѕ РїРѕРґС‚РІРµСЂР¶РґРµРЅР°!</b>\n\nР’Р°Рј РЅР°С‡РёСЃР»РµРЅРѕ +{count_to_add} РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹С… РіРµРЅРµСЂР°С†РёР№ Р°СЂС‚РѕРІ. Р’СЃРµРіРѕ РґРѕСЃС‚СѓРїРЅРѕ РіРµРЅРµСЂР°С†РёР№: {total_l}.")
            t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, t, reply_markup=m)
            return

    # 2. РћР‘Р РђР‘РћРўРљРђ РР—РћР‘Р РђР–Р•РќРРЇ (РџР•Р РЎРћРќРђР– РџРћ Р¤РћРўРћ)
    if "photo" in msg and m_sess.get("state") == "awaiting_char_photo":
        photo_list = msg.get("photo", [])
        if photo_list:
            send_message(token, m_chat, "рџ”Ќ <i>Р—Р°РіСЂСѓР¶Р°СЋ С„РѕС‚Рѕ Рё РїРµСЂРµРґР°СЋ РІ РР РґР»СЏ Р°РЅР°Р»РёР·Р° РІРЅРµС€РЅРѕСЃС‚Рё РїРµСЂСЃРѕРЅР°Р¶Р°...</i>")
            
            def _bg_photo_process():
                try:
                    file_id = photo_list[-1]["file_id"]
                    file_path = get_file(token, file_id)
                    if not file_path:
                        send_message(token, m_chat, "РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РїСѓС‚СЊ Рє С„Р°Р№Р»Сѓ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ РІ Telegram.")
                        return

                    img_bytes = download_file(token, file_path)
                    if not img_bytes:
                        send_message(token, m_chat, "РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєР°С‡Р°С‚СЊ С„РѕС‚Рѕ РёР· Telegram.")
                        return

                    char_name, tags = describe_character_by_photo(img_bytes)
                    if not char_name or not tags:
                        send_message(
                            token,
                            m_chat,
                            "вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ РЅР°РґС‘Р¶РЅРѕ СЂР°Р·РѕР±СЂР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ. "
                            "РџСЂРµР¶РЅРёР№ РїРµСЂСЃРѕРЅР°Р¶ СЃРѕС…СЂР°РЅС‘РЅ. РџРѕРїСЂРѕР±СѓР№С‚Рµ РґСЂСѓРіРѕРµ С„РѕС‚Рѕ РёР»Рё PNG-Р°СЂС‚."
                        )
                        return

                    # РџРѕРєР° РР СЂР°Р±РѕС‚Р°Р», РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РјРѕРі РѕС‚РјРµРЅРёС‚СЊ РѕРїРµСЂР°С†РёСЋ РёР»Рё РІС‹Р±СЂР°С‚СЊ РґСЂСѓРіРѕРµ.
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
                        f"вњ… <b>РџРµСЂСЃРѕРЅР°Р¶ СѓСЃРїРµС€РЅРѕ СЂР°СЃРїРѕР·РЅР°РЅ РїРѕ С„РѕС‚Рѕ!</b>\n\n"
                        f"рџ‘¤ <b>РРјСЏ / РћРїРёСЃР°РЅРёРµ:</b> {html.escape(char_name)}\n"
                        f"рџ“ќ <b>Danbooru-С‚РµРіРё РІРЅРµС€РЅРѕСЃС‚Рё:</b>\n<code>{html.escape(tags)}</code>\n\n"
                        f"РџР°СЂР°РјРµС‚СЂС‹ РїРµСЂСЃРѕРЅР°Р¶Р° СѓСЃС‚Р°РЅРѕРІР»РµРЅС‹ РІ СЃРµСЃСЃРёСЋ. РќР°Р¶РјРёС‚Рµ <b>[рџљЂ РЎР“Р•РќР•Р РР РћР’РђРўР¬ РђР Рў]</b> РґР»СЏ РіРµРЅРµСЂР°С†РёРё!"
                    )
                    t_main, m_main = make_main_menu(m_sess, user_id=u_id, username=u_name)
                    send_message(token, m_chat, caption_resp)
                    send_message(token, m_chat, t_main, reply_markup=m_main)
                except Exception as e:
                    send_message(token, m_chat, f"РћС€РёР±РєР° РїСЂРё СЂР°СЃРїРѕР·РЅР°РІР°РЅРёРё РїРµСЂСЃРѕРЅР°Р¶Р° РїРѕ С„РѕС‚Рѕ: {e}")

            threading.Thread(target=_bg_photo_process, daemon=True).start()
            return

    # 3. РўР•РљРЎРўРћР’Р«Р• РЎРћРћР‘Р©Р•РќРРЇ
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
                    "рџЋ‰ <b>Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ РІ GummyFlux!</b>\n\n"
                    "Р’С‹ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°Р»РёСЃСЊ РїРѕ РїРµСЂСЃРѕРЅР°Р»СЊРЅРѕРјСѓ РїСЂРёРіР»Р°С€РµРЅРёСЋ РґСЂСѓРіР°. "
                    "Р’Р°Рј РЅР°С‡РёСЃР»РµРЅР° <b>+1 СЃС‚Р°СЂС‚РѕРІР°СЏ Р±РѕРЅСѓСЃРЅР°СЏ РіРµРЅРµСЂР°С†РёСЏ</b> СЃРІРµСЂС… Р»РёРјРёС‚Р°!\n\n"
                    "РџСЂРёСЏС‚РЅРѕРіРѕ С‚РІРѕСЂС‡РµСЃС‚РІР°!"
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
            "в„№пёЏ <b>РЎРїСЂР°РІРєР° РїРѕ GummyFlux Bot</b>\n\n"
            "вЂў РќР°Р¶РјРёС‚Рµ <b>/menu</b>, С‡С‚РѕР±С‹ РѕС‚РєСЂС‹С‚СЊ РїР°РЅРµР»СЊ СѓРїСЂР°РІР»РµРЅРёСЏ РіРµРЅРµСЂР°С†РёРµР№ Р°СЂС‚РѕРІ.\n"
            "вЂў Р’С‹ РјРѕР¶РµС‚Рµ РІС‹Р±СЂР°С‚СЊ РіРѕС‚РѕРІРѕРіРѕ РїРµСЂСЃРѕРЅР°Р¶Р°, РїРѕР·Сѓ Рё РѕРєСЂСѓР¶РµРЅРёРµ РёР»Рё РѕРїРёСЃР°С‚СЊ РїРµСЂСЃРѕРЅР°Р¶Р° С‡РµСЂРµР· РР Рё РїРѕ С„РѕС‚Рѕ.\n"
            "вЂў Р§С‚РѕР±С‹ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РїРѕР»РЅРѕСЃС‚СЊСЋ СЃРІРѕР№ РїСЂРѕРјС‚, РІС‹Р±РµСЂРёС‚Рµ СЂР°Р·РґРµР» В«вњЌпёЏ РЎРІРѕР№ РєР°СЃС‚РѕРјРЅС‹Р№ РїСЂРѕРјС‚В» РІ РјРµРЅСЋ РёР»Рё РѕС‚РїСЂР°РІСЊС‚Рµ РѕРїРёСЃР°РЅРёРµ РІ С‡Р°С‚.\n"
            "вЂў РљР°Р¶РґС‹Р№ РґРµРЅСЊ РІР°Рј РґРѕСЃС‚СѓРїРЅРѕ Р±РµСЃРїР»Р°С‚РЅРѕРµ РєРѕР»РёС‡РµСЃС‚РІРѕ РіРµРЅРµСЂР°С†РёР№, Р° РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ РјРѕР¶РЅРѕ РїСЂРёРѕР±СЂРµСЃС‚Рё С‡РµСЂРµР· Telegram Stars РёР»Рё РїРѕР»СѓС‡РёС‚СЊ Р·Р° РїСЂРёРіР»Р°С€РµРЅРёРµ РґСЂСѓР·РµР№."
        )
        t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
        send_message(token, m_chat, help_text, reply_markup=m)

    elif text == "/admin" and is_admin(u_id, u_name):
        t, m = make_admin_menu()
        send_message(token, m_chat, t, reply_markup=m)

    elif text in ("/stop", "/shutdown") and is_admin(u_id, u_name):
        send_message(token, m_chat, "рџ›‘ <b>РРЅРёС†РёРёСЂРѕРІР°РЅ РїСЂРѕС†РµСЃСЃ РІС‹РєР»СЋС‡РµРЅРёСЏ Р±РѕС‚Р°...</b>")
        perform_safe_shutdown(token, m_chat, reason=f"РљРѕРјР°РЅРґР° {text} РѕС‚ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°")

    elif text == "/restart" and is_admin(u_id, u_name):
        send_message(token, m_chat, "рџ”„ <b>РРЅРёС†РёРёСЂРѕРІР°РЅ РїРµСЂРµР·Р°РїСѓСЃРє Р±РѕС‚Р°...</b>")
        perform_safe_reload(token, m_chat)

    elif is_admin(u_id, u_name) and m_sess.get("state") == "awaiting_admin_search_user":
        target_uid, user_obj = find_user_by_query(text)
        if target_uid:
            m_sess["state"] = "idle"
            t, m = render_admin_user_card(target_uid)
            send_message(token, m_chat, t, reply_markup=m)
        else:
            kb = [
                [{"text": "рџ”Ќ РџРѕРїСЂРѕР±РѕРІР°С‚СЊ СЃРЅРѕРІР°", "callback_data": "admin_search_user"}],
                [{"text": "в—ЂпёЏ РќР°Р·Р°Рґ Рє РїРѕР»СЊР·РѕРІР°С‚РµР»СЏРј", "callback_data": "admin_users_page_0"}]
            ]
            send_message(token, m_chat, f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ '{html.escape(text)}' РЅРµ РЅР°Р№РґРµРЅ РІ Р±Р°Р·Рµ РґР°РЅРЅС‹С… Р±РѕС‚Р°.", reply_markup={"inline_keyboard": kb})

    elif is_admin(u_id, u_name) and m_sess.get("state") == "awaiting_custom_base_limit":
        target_uid = m_sess.get("target_user_id")
        if text.isdigit() and 0 <= int(text) <= 1000:
            set_user_base_limit(target_uid, int(text))
            m_sess["state"] = "idle"
            t, m = render_admin_user_card(target_uid)
            send_message(token, m_chat, f"вњ… Р‘Р°Р·РѕРІС‹Р№ Р»РёРјРёС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ СѓСЃС‚Р°РЅРѕРІР»РµРЅ: {text} РіРµРЅ./РґРµРЅСЊ.\n\n" + t, reply_markup=m)
        else:
            kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": f"admin_user_{target_uid}"}]]
            send_message(token, m_chat, "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІРІРµРґРёС‚Рµ С‡РёСЃР»Рѕ РѕС‚ 0 РґРѕ 1000.", reply_markup={"inline_keyboard": kb})

    elif is_admin(u_id, u_name) and m_sess.get("state") == "awaiting_custom_grant":
        target_uid = m_sess.get("target_user_id")
        if text.isdigit() and 1 <= int(text) <= 10000:
            add_user_bonus_generations(target_uid, int(text))
            try:
                send_message(token, target_uid, f"рџЋЃ РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ РЅР°С‡РёСЃР»РёР» РІР°Рј +{text} РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹С… РіРµРЅРµСЂР°С†РёР№ Р°СЂС‚РѕРІ! РџСЂРёСЏС‚РЅРѕРіРѕ С‚РІРѕСЂС‡РµСЃС‚РІР°!")
            except Exception:
                pass
            m_sess["state"] = "idle"
            t, m = render_admin_user_card(target_uid)
            send_message(token, m_chat, f"вњ… РџРѕР»СЊР·РѕРІР°С‚РµР»СЋ СѓСЃРїРµС€РЅРѕ РЅР°С‡РёСЃР»РµРЅРѕ +{text} Р±РѕРЅСѓСЃРЅС‹С… РіРµРЅРµСЂР°С†РёР№!\n\n" + t, reply_markup=m)
        else:
            kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": f"admin_user_{target_uid}"}]]
            send_message(token, m_chat, "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІРІРµРґРёС‚Рµ РїРѕР»РѕР¶РёС‚РµР»СЊРЅРѕРµ С‡РёСЃР»Рѕ РѕС‚ 1 РґРѕ 10000.", reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_custom_samples":
        if text.isdigit():
            val = int(text)
            if is_admin(u_id, u_name):
                if 5 <= val <= 60:
                    m_sess["steps"] = val
                    m_sess["state"] = "idle"
                    save_sessions()
                    t, m = make_samples_menu(m_sess, user_id=u_id, username=u_name)
                    send_message(token, m_chat, f"вњ… РљРѕР»РёС‡РµСЃС‚РІРѕ С€Р°РіРѕРІ СЃРµРјРїР»РёСЂРѕРІР°РЅРёСЏ СѓСЃС‚Р°РЅРѕРІР»РµРЅРѕ: <b>{val}</b>.\n\n" + t, reply_markup=m)
                else:
                    kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "menu_samples"}]]
                    send_message(token, m_chat, "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІРІРµРґРёС‚Рµ С‡РёСЃР»Рѕ С€Р°РіРѕРІ РѕС‚ 5 РґРѕ 60.", reply_markup={"inline_keyboard": kb})
            else:
                if 15 <= val <= 30:
                    m_sess["steps"] = val
                    m_sess["state"] = "idle"
                    save_sessions()
                    t, m = make_samples_menu(m_sess, user_id=u_id, username=u_name)
                    send_message(token, m_chat, f"вњ… РљРѕР»РёС‡РµСЃС‚РІРѕ С€Р°РіРѕРІ СЃРµРјРїР»РёСЂРѕРІР°РЅРёСЏ СѓСЃС‚Р°РЅРѕРІР»РµРЅРѕ: <b>{val}</b>.\n\n" + t, reply_markup=m)
                else:
                    kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "menu_samples"}]]
                    send_message(token, m_chat, "Р”Р»СЏ РІР°С€РµРіРѕ Р°РєРєР°СѓРЅС‚Р° РґРѕСЃС‚СѓРїРЅРѕ РѕС‚ 15 РґРѕ 30 С€Р°РіРѕРІ.", reply_markup={"inline_keyboard": kb})
        else:
            kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "menu_samples"}]]
            min_s, max_s = (5, 60) if is_admin(u_id, u_name) else (15, 30)
            send_message(token, m_chat, f"РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІРІРµРґРёС‚Рµ РєРѕСЂСЂРµРєС‚РЅРѕРµ С‡РёСЃР»Рѕ РѕС‚ {min_s} РґРѕ {max_s}.", reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_custom_cfg":
        try:
            val = float(text.replace(",", ".").strip())
            if 1.0 <= val <= 15.0:
                val = round(val, 1)
                m_sess["cfg_scale"] = val
                m_sess["state"] = "idle"
                save_sessions()
                t, m = make_cfg_menu(m_sess)
                send_message(token, m_chat, f"вњ… РџР°СЂР°РјРµС‚СЂ СЃРёР»С‹ РїСЂРѕРјРїС‚Р° (CFG Scale) СѓСЃС‚Р°РЅРѕРІР»РµРЅ: <b>{val}</b>.\n\n" + t, reply_markup=m)
            else:
                kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "menu_cfg"}]]
                send_message(token, m_chat, "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІРІРµРґРёС‚Рµ С‡РёСЃР»Рѕ РѕС‚ <b>1.0</b> РґРѕ <b>15.0</b>.", reply_markup={"inline_keyboard": kb})
        except ValueError:
            kb = [[{"text": "в—ЂпёЏ РћС‚РјРµРЅР°", "callback_data": "menu_cfg"}]]
            send_message(token, m_chat, "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІРІРµРґРёС‚Рµ РєРѕСЂСЂРµРєС‚РЅРѕРµ С‡РёСЃР»Рѕ РѕС‚ <b>1.0</b> РґРѕ <b>15.0</b> (РЅР°РїСЂРёРјРµСЂ: <code>5.5</code> РёР»Рё <code>7.0</code>).", reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_ai_char_name":
        send_message(token, m_chat, f"рџ”Ќ <i>РР РЅР°С…РѕРґРёС‚ РѕРїРёСЃР°РЅРёРµ Рё С‡РµС‚РєРёРµ Danbooru-С‚РµРіРё РґР»СЏ '{html.escape(text)}'...</i>")

        def _bg_name_tagging():
            tags = describe_character_by_name(text)
            m_sess["char_name"] = text.title()
            m_sess["char_prompt"] = tags
            m_sess["state"] = "idle"
            save_sessions()
            res_text = (
                f"вњ… <b>Р’РЅРµС€РЅРѕСЃС‚СЊ '{html.escape(text.title())}' СЃС„РѕСЂРјРёСЂРѕРІР°РЅР° С‡РµСЂРµР· РР!</b>\n\n"
                f"<b>Danbooru-С‚РµРіРё:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"РџР°СЂР°РјРµС‚СЂС‹ РїРµСЂСЃРѕРЅР°Р¶Р° СѓСЃС‚Р°РЅРѕРІР»РµРЅС‹ РІ СЃРµСЃСЃРёСЋ."
            )
            t_main, m_main = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, res_text)
            send_message(token, m_chat, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_name_tagging, daemon=True).start()

    elif m_sess.get("state") == "awaiting_char_photo":
        send_message(token, m_chat, "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РѕС‚РїСЂР°РІСЊС‚Рµ РёРјРµРЅРЅРѕ РёР·РѕР±СЂР°Р¶РµРЅРёРµ РїРµСЂСЃРѕРЅР°Р¶Р° (РІР»РѕР¶РµРЅРёРµРј 'Р¤РѕС‚Рѕ').")

    elif m_sess.get("state") == "awaiting_char_query":
        send_message(token, m_chat, f"рџ”Ќ <i>РС‰Сѓ РїРµСЂСЃРѕРЅР°Р¶Р° '{html.escape(text)}' Рё СЃРѕСЃС‚Р°РІР»СЏСЋ РїРѕРґСЂРѕР±РЅС‹Р№ Danbooru-РїСЂРѕРјС‚ С‡РµСЂРµР· РР...</i>")

        def _bg_search_and_ai():
            results = search_online_characters(text)
            m_sess["search_target"] = text
            stored_searches[f"{m_chat}_char"] = results

            # Р•СЃР»Рё РІ Р±Р°Р·Рµ РЅР°Р№РґРµРЅ РєР°РЅРѕРЅРёС‡РЅС‹Р№ С‚РµРі (РЅР°РїСЂРёРјРµСЂ, v_(murder_drones)), РїРµСЂРµРґР°РµРј РµРіРѕ РР РґР»СЏ РёРґРµР°Р»СЊРЅРѕР№ С‚РѕС‡РЅРѕСЃС‚Рё
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
                f"вњ… <b>РџРµСЂСЃРѕРЅР°Р¶ '{html.escape(char_title)}' СѓСЃРїРµС€РЅРѕ СЂР°СЃРїРѕР·РЅР°РЅ Рё РѕРїРёСЃР°РЅ РР!</b>\n\n"
                f"<b>Danbooru-С‚РµРіРё РІРЅРµС€РЅРѕСЃС‚Рё:</b>\n<code>{html.escape(tags)}</code>\n\n"
                f"РџР°СЂР°РјРµС‚СЂС‹ РїРµСЂСЃРѕРЅР°Р¶Р° СѓСЃС‚Р°РЅРѕРІР»РµРЅС‹. РќР°Р¶РјРёС‚Рµ <b>[рџљЂ РЎР“Р•РќР•Р РР РћР’РђРўР¬ РђР Рў]</b> РґР»СЏ СЃРѕР·РґР°РЅРёСЏ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ."
            )

            kb = []
            if len(results) > 1:
                alt_row = []
                for idx, r in enumerate(results[1:4], 1):
                    alt_row.append({"text": f"рџ‘¤ {r[0].title()}", "callback_data": f"select_char_{idx}"})
                if alt_row:
                    kb.append(alt_row)

            t_main, m_main = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, res_text, reply_markup={"inline_keyboard": kb} if kb else None)
            send_message(token, m_chat, t_main, reply_markup=m_main)

        threading.Thread(target=_bg_search_and_ai, daemon=True).start()

    elif m_sess.get("state") == "awaiting_pose_query":
        send_message(token, m_chat, f"Р’С‹РїРѕР»РЅСЏСЋ РѕРЅР»Р°Р№РЅ РїРѕРёСЃРє РїРѕР·С‹: '{text}'...")
        results = search_online_poses(text)
        m_sess["search_target"] = text
        stored_searches[f"{m_chat}_pose"] = results

        kb = []
        for idx, r in enumerate(results):
            kb.append([{"text": f"[{r[0].title()}]", "callback_data": f"select_pose_{idx}"}])

        kb.append([{"text": f"[РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ '{text}' РєР°Рє РµСЃС‚СЊ]", "callback_data": "custom_pose_apply"}])
        kb.append([{"text": "в—ЂпёЏ РќР°Р·Р°Рґ РІ РІС‹Р±РѕСЂ РїРѕР·С‹", "callback_data": "menu_pose"}])

        reply_text = f"Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° РїРѕР· РґР»СЏ '{text}':\nР’С‹Р±РµСЂРёС‚Рµ РЅР°Р№РґРµРЅРЅСѓСЋ РїРѕР·Сѓ РёР»Рё РїСЂРёРјРµРЅРёС‚Рµ РІРІРµРґРµРЅРЅС‹Р№ С‚РµРєСЃС‚:"
        send_message(token, m_chat, reply_text, reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_env_query":
        send_message(token, m_chat, f"Р’С‹РїРѕР»РЅСЏСЋ РѕРЅР»Р°Р№РЅ РїРѕРёСЃРє РѕРєСЂСѓР¶РµРЅРёСЏ: '{text}'...")
        results = search_online_environment(text)
        m_sess["search_target"] = text
        stored_searches[f"{m_chat}_env"] = results

        kb = []
        for idx, r in enumerate(results):
            kb.append([{"text": f"[{r[0].title()}]", "callback_data": f"select_env_{idx}"}])

        kb.append([{"text": f"[РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ '{text}' РєР°Рє РµСЃС‚СЊ]", "callback_data": "custom_env_apply"}])
        kb.append([{"text": "вќЊ Р‘РµР· РѕРєСЂСѓР¶РµРЅРёСЏ (РћС‡РёСЃС‚РёС‚СЊ)", "callback_data": "clear_env"}])
        kb.append([{"text": "в—ЂпёЏ РќР°Р·Р°Рґ РІ РІС‹Р±РѕСЂ РѕРєСЂСѓР¶РµРЅРёСЏ", "callback_data": "menu_env"}])

        reply_text = f"Р РµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР° РѕРєСЂСѓР¶РµРЅРёСЏ РґР»СЏ '{text}':\nР’С‹Р±РµСЂРёС‚Рµ РЅР°Р№РґРµРЅРЅСѓСЋ Р»РѕРєР°С†РёСЋ РёР»Рё РїСЂРёРјРµРЅРёС‚Рµ РІРІРµРґРµРЅРЅС‹Р№ С‚РµРєСЃС‚:"
        send_message(token, m_chat, reply_text, reply_markup={"inline_keyboard": kb})

    elif m_sess.get("state") == "awaiting_resolution":
        clean_res = text.lower().replace("С…", "x").replace("*", "x").replace(" ", "")
        parts = clean_res.split("x")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            w = int(parts[0])
            h = int(parts[1])
            if w > 1500 or h > 1500:
                send_message(token, m_chat, "РћС€РёР±РєР°: СЃС‚РѕСЂРѕРЅС‹ СЂР°Р·СЂРµС€РµРЅРёСЏ РЅРµ РјРѕРіСѓС‚ РїСЂРµРІС‹С€Р°С‚СЊ 1500 РїРёРєСЃРµР»РµР№.")
            elif w < 512 or h < 512:
                send_message(token, m_chat, "РћС€РёР±РєР°: РјРёРЅРёРјР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ СЃС‚РѕСЂРѕРЅС‹ СЃРѕСЃС‚Р°РІР»СЏРµС‚ 512 РїРёРєСЃРµР»РµР№.")
            else:
                w = (w // 64) * 64
                h = (h // 64) * 64
                w = min(w, 1472)
                h = min(h, 1472)
                m_sess["width"] = w
                m_sess["height"] = h
                m_sess["state"] = "idle"
                save_sessions()
                send_message(token, m_chat, f"РЈСЃС‚Р°РЅРѕРІР»РµРЅРѕ СЂР°Р·СЂРµС€РµРЅРёРµ: {w}x{h}.")
                t, m = make_settings_menu(m_sess, user_id=u_id, username=u_name)
                send_message(token, m_chat, t, reply_markup=m)
        else:
            send_message(token, m_chat, "РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚. Р’РІРµРґРёС‚Рµ СЂР°Р·РјРµСЂС‹ РІ С„РѕСЂРјР°С‚Рµ РЁРР РРќРђxР’Р«РЎРћРўРђ (РЅР°РїСЂРёРјРµСЂ, 896x1152).")

    else:
        # РџСЂРѕРІРµСЂСЏРµРј, СЏРІР»СЏРµС‚СЃСЏ Р»Рё СЃРѕРѕР±С‰РµРЅРёРµ РѕР±С‹С‡РЅС‹Рј РїСЂРёРІРµС‚СЃС‚РІРёРµРј РёР»Рё РІРѕРїСЂРѕСЃРѕРј
        clean_low = text.lower().strip()
        greetings = {"РїСЂРёРІРµС‚", "С…Р°Р№", "Р·РґСЂР°РІСЃС‚РІСѓР№С‚Рµ", "РґРѕР±СЂС‹Р№ РґРµРЅСЊ", "РґРѕР±СЂС‹Р№ РІРµС‡РµСЂ", "РєСѓ", "hello", "hi", "hey", "СЃС‚Р°СЂС‚", "РїРѕРјРѕС‰СЊ", "help", "РјРµРЅСЋ"}
        if clean_low in greetings:
            m_sess["state"] = "idle"
            t, m = make_main_menu(m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, "РџСЂРёРІРµС‚! Р”Р»СЏ РІС‹Р±РѕСЂР° РїРµСЂСЃРѕРЅР°Р¶Р°, РїРѕР·С‹ РёР»Рё СЃРѕР·РґР°РЅРёСЏ Р°СЂС‚Р° РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РјРµРЅСЋ:", reply_markup=m)
        else:
            # РџСЂРѕРёР·РІРѕР»СЊРЅС‹Р№ С‚РµРєСЃС‚ / РєР°СЃС‚РѕРјРЅС‹Р№ РїСЂРѕРјС‚: РЅРµ Р·Р°РїСѓСЃРєР°РµРј РіРµРЅРµСЂР°С†РёСЋ СЃСЂР°Р·Сѓ, Р° СЃРїСЂР°С€РёРІР°РµРј РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ!
            m_sess["pending_custom_prompt"] = text
            m_sess["state"] = "idle"
            t, m = make_confirm_custom_menu(text, m_sess, user_id=u_id, username=u_name)
            send_message(token, m_chat, t, reply_markup=m)

