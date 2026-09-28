import os
import json
import time
import uuid
import threading
import html
from datetime import datetime
from bot.config import DB_PATH, db_lock, load_config

def load_db():
    with db_lock:
        if os.path.exists(DB_PATH):
            try:
                with open(DB_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"users": {}, "history": [], "messages": []}

def save_db(data):
    with db_lock:
        try:
            temp_path = DB_PATH + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, DB_PATH)
        except Exception as e:
            print(f"Error saving DB: {e}", flush=True)

def is_admin(user_id, username=None):
    cfg = load_config()
    admin_id = str(cfg.get("chat_id", "")).strip()
    admin_uname = str(cfg.get("admin_username", "")).strip().lstrip("@").lower()
    if user_id and admin_id and str(user_id) == admin_id:
        return True
    if username and admin_uname and username.lower().lstrip("@") == admin_uname:
        return True
    return False

def touch_user(user_id, username=None, first_name=None):
    with db_lock:
        uid = str(user_id)
        db = load_db()
        today = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        user = db["users"].get(uid, {
            "user_id": uid,
            "username": username or "",
            "first_name": first_name or "",
            "daily_date": today,
            "daily_count": 0,
            "base_daily_limit": 3,
            "bonus_credits": 0,
            "total_count": 0,
            "total_stars": 0,
            "last_seen": now_str,
            "referred_by": None,
            "referrals_count": 0,
            "referral_bonus_earned": 0
        })
        if "base_daily_limit" not in user:
            user["base_daily_limit"] = 3
        if "referred_by" not in user:
            user["referred_by"] = None
        if "referrals_count" not in user:
            user["referrals_count"] = 0
        if "referral_bonus_earned" not in user:
            user["referral_bonus_earned"] = 0

        if username:
            user["username"] = username
        if first_name:
            user["first_name"] = first_name
        user["last_seen"] = now_str

        if user.get("daily_date") != today:
            user["daily_date"] = today
            user["daily_count"] = 0

        db["users"][uid] = user
        save_db(db)
        return user

def get_user_limits_status(user_id, username=None):
    if is_admin(user_id, username):
        return True, 9999, 9999, 9999
    user = touch_user(user_id, username)
    daily_count = user.get("daily_count", 0)
    base_lim = user.get("base_daily_limit", 3)
    free_left = max(0, base_lim - daily_count)
    bonus_credits = user.get("bonus_credits", 0)
    total_left = free_left + bonus_credits
    return False, free_left, bonus_credits, total_left

def consume_user_generation(user_id, username=None):
    with db_lock:
        if is_admin(user_id, username):
            touch_user(user_id, username)
            db = load_db()
            uid = str(user_id)
            if uid in db["users"]:
                db["users"][uid]["total_count"] = db["users"][uid].get("total_count", 0) + 1
                save_db(db)
            return True, "admin", "admin"

        touch_user(user_id, username)
        db = load_db()
        uid = str(user_id)
        user = db["users"].get(uid)
        if not user:
            return False, "error", None

        today = datetime.now().strftime("%Y-%m-%d")
        if user.get("daily_date") != today:
            user["daily_date"] = today
            user["daily_count"] = 0

        daily_count = user.get("daily_count", 0)
        base_lim = user.get("base_daily_limit", 3)
        bonus_credits = user.get("bonus_credits", 0)

        if daily_count < base_lim:
            user["daily_count"] = daily_count + 1
            user["total_count"] = user.get("total_count", 0) + 1
            save_db(db)
            return True, f"Использован бесплатный запрос ({user['daily_count']}/{base_lim})", "free"
        elif bonus_credits > 0:
            user["bonus_credits"] = bonus_credits - 1
            user["total_count"] = user.get("total_count", 0) + 1
            save_db(db)
            return True, f"Использован бонусный запрос (осталось: {user['bonus_credits']})", "bonus"
        else:
            return False, "Лимит исчерпан", None

def refund_user_generation(user_id, consumed_type):
    """
    Возвращает списанную генерацию пользователю в случае сбоя WebUI или сети.
    consumed_type: 'bonus' (вернуть бонусные кредиты) или 'free' (уменьшить daily_count).
    """
    if not consumed_type or consumed_type == "admin":
        return True
    with db_lock:
        db = load_db()
        uid = str(user_id)
        user = db.get("users", {}).get(uid)
        if not user:
            return False
        
        if user.get("total_count", 0) > 0:
            user["total_count"] -= 1

        if consumed_type == "bonus":
            user["bonus_credits"] = user.get("bonus_credits", 0) + 1
        elif consumed_type == "free":
            if user.get("daily_count", 0) > 0:
                user["daily_count"] -= 1
        save_db(db)
        return True

def add_bonus_credits(user_id, count=1, stars=2):
    with db_lock:
        touch_user(user_id)
        db = load_db()
        uid = str(user_id)
        if uid in db["users"]:
            db["users"][uid]["bonus_credits"] = db["users"][uid].get("bonus_credits", 0) + count
            db["users"][uid]["total_stars"] = db["users"][uid].get("total_stars", 0) + stars
            save_db(db)

def process_referral(new_user_id, inviter_id, token, send_message_func):
    new_uid = str(new_user_id)
    inv_uid = str(inviter_id)
    if new_uid == inv_uid:
        return False, "self_referral"

    with db_lock:
        db = load_db()
        users = db.get("users", {})
        if inv_uid not in users:
            return False, "inviter_not_found"

        new_user = users.get(new_uid)
        if new_user and (new_user.get("referred_by") or new_user.get("total_count", 0) > 0):
            return False, "already_registered"

        if not new_user:
            touch_user(new_uid)
            db = load_db()
            users = db.get("users", {})

        users[new_uid]["referred_by"] = inv_uid
        users[new_uid]["bonus_credits"] = users[new_uid].get("bonus_credits", 0) + 1

        inv_user = users[inv_uid]
        inv_user["bonus_credits"] = inv_user.get("bonus_credits", 0) + 2
        inv_user["referrals_count"] = inv_user.get("referrals_count", 0) + 1
        inv_user["referral_bonus_earned"] = inv_user.get("referral_bonus_earned", 0) + 2

        save_db(db)

    try:
        u_info = users.get(new_uid, {})
        u_fn = u_info.get("first_name")
        u_un = u_info.get("username")
        new_name = u_fn or ((f"@{u_un}") if u_un else f"ID {new_uid}")
        new_name_esc = html.escape(str(new_name))
        inv_msg = (
            "🎁 <b>Новый пользователь по вашей ссылке!</b>\n\n"
            f"Пользователь <b>{new_name_esc}</b> присоединился к GummyFlux.\n"
            f"Вам начислено <b>+2 бонусных генерации</b> (всего приглашено друзей: {inv_user['referrals_count']})."
        )
        send_message_func(token, inv_uid, inv_msg)
    except Exception as e:
        print(f"Error notifying inviter: {e}", flush=True)

    return True, inv_uid

def get_user_referral_stats(user_id):
    db = load_db()
    u = db.get("users", {}).get(str(user_id), {})
    return u.get("referrals_count", 0), u.get("referral_bonus_earned", 0)

def set_user_base_limit(user_id, new_limit):
    with db_lock:
        touch_user(user_id)
        db = load_db()
        uid = str(user_id)
        if uid in db["users"]:
            db["users"][uid]["base_daily_limit"] = max(0, int(new_limit))
            save_db(db)
            return True, db["users"][uid]["base_daily_limit"]
        return False, 3

def add_user_bonus_generations(user_id, count):
    with db_lock:
        touch_user(user_id)
        db = load_db()
        uid = str(user_id)
        if uid in db["users"]:
            if count == "reset":
                db["users"][uid]["bonus_credits"] = 0
            else:
                db["users"][uid]["bonus_credits"] = max(0, db["users"][uid].get("bonus_credits", 0) + int(count))
            save_db(db)
            return True, db["users"][uid]["bonus_credits"]
        return False, 0

def reset_user_daily_count(user_id):
    with db_lock:
        touch_user(user_id)
        db = load_db()
        uid = str(user_id)
        if uid in db["users"]:
            db["users"][uid]["daily_count"] = 0
            save_db(db)
            return True
        return False

def reset_all_users_daily_limits_async(token, admin_chat_id, send_message_func):
    def _worker():
        today = datetime.now().strftime("%Y-%m-%d")
        reset_count = 0
        notified_count = 0
        target_uids = []

        with db_lock:
            db = load_db()
            users = db.get("users", {})
            for uid, u in users.items():
                u["daily_count"] = 0
                u["daily_date"] = today
                reset_count += 1
                if not is_admin(uid, u.get("username")) and str(uid) != str(admin_chat_id):
                    target_uids.append((uid, u.get("base_daily_limit", 3)))

            save_db(db)

        for uid, base_lim in target_uids:
            try:
                notify_text = (
                    "🔄 <b>Дневные лимиты генераций сброшены!</b>\n\n"
                    f"Администратор досрочно обновил лимиты для всех пользователей бота.\n"
                    f"Вам снова доступно <b>{base_lim}</b> бесплатных генераций на сегодня!\n\n"
                    "Приятного творчества в GummyFlux!"
                )
                res = send_message_func(token, uid, notify_text)
                if res and res.get("ok"):
                    notified_count += 1
                time.sleep(0.05)
            except Exception:
                pass

        summary_msg = (
            f"✅ <b>МАССОВЫЙ СБРОС ЛИМИТОВ УСПЕШНО ЗАВЕРШЕН</b>\n\n"
            f"👥 Обнулены суточные счетчики для: <b>{reset_count}</b> пользователей\n"
            f"📩 Доставлено персональных уведомлений: <b>{notified_count}</b> из {len(target_uids)}."
        )
        kb = [[{"text": "◀️ В панель пользователей", "callback_data": "admin_users_page_0"}]]
        send_message_func(token, admin_chat_id, summary_msg, reply_markup={"inline_keyboard": kb})

    threading.Thread(target=_worker, daemon=True).start()

def find_user_by_query(query_str):
    if not query_str:
        return None, None
    q = query_str.strip().lower().lstrip("@")
    db = load_db()
    users = db.get("users", {})
    if q in users:
        return q, users[q]
    for uid, u in users.items():
        if (u.get("username") or "").lower() == q:
            return uid, u
    for uid, u in users.items():
        if q in (u.get("username") or "").lower():
            return uid, u
    for uid, u in users.items():
        if q in (u.get("first_name") or "").lower():
            return uid, u
    return None, None

def log_generation(user_id, username, first_name, mode, char_name, pose_name, env_name, resolution, prompt, elapsed, is_custom=False, image_path="", img_id=None):
    with db_lock:
        db = load_db()
        entry = {
            "id": img_id or uuid.uuid4().hex[:8],
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": str(user_id),
            "username": username or "без юзернейма",
            "first_name": first_name or "",
            "mode": mode,
            "char": char_name,
            "pose": pose_name,
            "env": env_name,
            "res": resolution,
            "prompt": prompt,
            "elapsed": elapsed,
            "is_custom": is_custom,
            "image_path": image_path
        }
        db["history"].insert(0, entry)
        db["history"] = db["history"][:200]
        save_db(db)

def log_message(user_id, username, text):
    with db_lock:
        db = load_db()
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": str(user_id),
            "username": username or "без юзернейма",
            "text": text
        }
        db["messages"].insert(0, entry)
        db["messages"] = db["messages"][:100]
        save_db(db)
