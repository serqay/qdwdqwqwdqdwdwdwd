import os
import time
import uuid
import threading
import html
import sqlite3
from datetime import datetime
from bot.config import DB_SQLITE_PATH, db_lock, load_config

def get_conn():
    conn = sqlite3.connect(DB_SQLITE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            daily_date TEXT,
            daily_count INTEGER DEFAULT 0,
            base_daily_limit INTEGER DEFAULT 3,
            bonus_credits INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            total_stars INTEGER DEFAULT 0,
            last_seen TEXT,
            referred_by TEXT,
            referrals_count INTEGER DEFAULT 0,
            referral_bonus_earned INTEGER DEFAULT 0,
            vip_until TEXT,
            language TEXT DEFAULT 'ru'
        )''')
        c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            time TEXT,
            user_id TEXT,
            username TEXT,
            first_name TEXT,
            mode TEXT,
            char TEXT,
            pose TEXT,
            env TEXT,
            res TEXT,
            prompt TEXT,
            elapsed REAL,
            is_custom BOOLEAN,
            image_path TEXT,
            seed INTEGER DEFAULT -1
        )''')
        c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            user_id TEXT,
            username TEXT,
            text TEXT
        )''')
        c.execute('''
        CREATE TABLE IF NOT EXISTS pc_notifies (
            chat_id TEXT PRIMARY KEY
        )''')
        conn.commit()
        conn.close()

init_db()

def load_db():
    # Backward compatibility for menus.py and handlers.py
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        
        c.execute("SELECT * FROM users")
        users = {str(row["user_id"]): dict(row) for row in c.fetchall()}
        
        c.execute("SELECT * FROM history ORDER BY time DESC LIMIT 200")
        history = [dict(row) for row in c.fetchall()]
        
        c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 100")
        messages = [dict(row) for row in c.fetchall()]
        
        c.execute("SELECT * FROM pc_notifies")
        pc_notifies = [row["chat_id"] for row in c.fetchall()]
        
        conn.close()
        
        return {
            "users": users,
            "history": history,
            "messages": messages,
            "pc_notifies": pc_notifies
        }

def save_db(data):
    # Deprecated - no longer needed since we write directly to SQLite.
    pass

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
        today = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_conn()
        c = conn.cursor()
        
        c.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        row = c.fetchone()
        
        if row:
            user = dict(row)
            if user.get("daily_date") != today:
                c.execute("UPDATE users SET daily_date = ?, daily_count = 0 WHERE user_id = ?", (today, uid))
                user["daily_date"] = today
                user["daily_count"] = 0
            
            updates = []
            params = []
            if username and user.get("username") != username:
                updates.append("username = ?")
                params.append(username)
                user["username"] = username
            if first_name and user.get("first_name") != first_name:
                updates.append("first_name = ?")
                params.append(first_name)
                user["first_name"] = first_name
                
            updates.append("last_seen = ?")
            params.append(now_str)
            user["last_seen"] = now_str
            
            params.append(uid)
            c.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params)
        else:
            c.execute('''
            INSERT INTO users (
                user_id, username, first_name, daily_date, daily_count, base_daily_limit,
                bonus_credits, total_count, total_stars, last_seen, referred_by,
                referrals_count, referral_bonus_earned, vip_until, language
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'ru')
            ''', (
                uid, username or "", first_name or "", today, 0, 3, 0, 0, 0, now_str, None, 0, 0
            ))
            c.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
            user = dict(c.fetchone())
            
        conn.commit()
        conn.close()
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
            conn = get_conn()
            conn.execute("UPDATE users SET total_count = total_count + 1 WHERE user_id = ?", (str(user_id),))
            conn.commit()
            conn.close()
            return True, "admin", "admin"

        user = touch_user(user_id, username)
        uid = str(user_id)
        
        daily_count = user.get("daily_count", 0)
        base_lim = user.get("base_daily_limit", 3)
        bonus_credits = user.get("bonus_credits", 0)

        conn = get_conn()
        c = conn.cursor()
        
        if daily_count < base_lim:
            c.execute("UPDATE users SET daily_count = daily_count + 1, total_count = total_count + 1 WHERE user_id = ?", (uid,))
            conn.commit()
            conn.close()
            return True, f"Использован бесплатный запрос ({daily_count + 1}/{base_lim})", "free"
        elif bonus_credits > 0:
            c.execute("UPDATE users SET bonus_credits = bonus_credits - 1, total_count = total_count + 1 WHERE user_id = ?", (uid,))
            conn.commit()
            conn.close()
            return True, f"Использован бонусный запрос (осталось: {bonus_credits - 1})", "bonus"
        else:
            conn.close()
            return False, "Лимит исчерпан", None

def refund_user_generation(user_id, consumed_type):
    if not consumed_type or consumed_type == "admin":
        return True
    with db_lock:
        uid = str(user_id)
        conn = get_conn()
        c = conn.cursor()
        
        c.execute("SELECT total_count, bonus_credits, daily_count FROM users WHERE user_id = ?", (uid,))
        row = c.fetchone()
        if not row:
            conn.close()
            return False
            
        if row["total_count"] > 0:
            c.execute("UPDATE users SET total_count = total_count - 1 WHERE user_id = ?", (uid,))
            
        if consumed_type == "bonus":
            c.execute("UPDATE users SET bonus_credits = bonus_credits + 1 WHERE user_id = ?", (uid,))
        elif consumed_type == "free":
            if row["daily_count"] > 0:
                c.execute("UPDATE users SET daily_count = daily_count - 1 WHERE user_id = ?", (uid,))
                
        conn.commit()
        conn.close()
        return True

def add_bonus_credits(user_id, count=1, stars=2):
    with db_lock:
        touch_user(user_id)
        conn = get_conn()
        conn.execute("UPDATE users SET bonus_credits = bonus_credits + ?, total_stars = total_stars + ? WHERE user_id = ?", (count, stars, str(user_id)))
        conn.commit()
        conn.close()

def process_referral(new_user_id, inviter_id, token, send_message_func):
    new_uid = str(new_user_id)
    inv_uid = str(inviter_id)
    if new_uid == inv_uid:
        return False, "self_referral"

    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        
        c.execute("SELECT * FROM users WHERE user_id = ?", (inv_uid,))
        inv_user = c.fetchone()
        if not inv_user:
            conn.close()
            return False, "inviter_not_found"

        c.execute("SELECT * FROM users WHERE user_id = ?", (new_uid,))
        new_user = c.fetchone()
        
        if new_user and (new_user["referred_by"] or new_user["total_count"] > 0):
            conn.close()
            return False, "already_registered"

        if not new_user:
            conn.close()
            touch_user(new_uid)
            conn = get_conn()
            c = conn.cursor()
            
        c.execute("UPDATE users SET referred_by = ?, bonus_credits = bonus_credits + 1 WHERE user_id = ?", (inv_uid, new_uid))
        c.execute("UPDATE users SET bonus_credits = bonus_credits + 2, referrals_count = referrals_count + 1, referral_bonus_earned = referral_bonus_earned + 2 WHERE user_id = ?", (inv_uid,))
        
        conn.commit()
        
        c.execute("SELECT referrals_count FROM users WHERE user_id = ?", (inv_uid,))
        refs_count = c.fetchone()["referrals_count"]
        
        c.execute("SELECT * FROM users WHERE user_id = ?", (new_uid,))
        u_info = c.fetchone()
        
        conn.close()

    try:
        u_fn = u_info["first_name"]
        u_un = u_info["username"]
        new_name = u_fn or ((f"@{u_un}") if u_un else f"ID {new_uid}")
        new_name_esc = html.escape(str(new_name))
        inv_msg = (
            "🎁 <b>Новый пользователь по вашей ссылке!</b>\n\n"
            f"Пользователь <b>{new_name_esc}</b> присоединился к GummyFlux.\n"
            f"Вам начислено <b>+2 бонусных генерации</b> (всего приглашено друзей: {refs_count})."
        )
        send_message_func(token, inv_uid, inv_msg)
    except Exception as e:
        print(f"Error notifying inviter: {e}", flush=True)

    return True, inv_uid

def get_user_referral_stats(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT referrals_count, referral_bonus_earned FROM users WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    if row:
        return row["referrals_count"], row["referral_bonus_earned"]
    return 0, 0

def set_user_base_limit(user_id, new_limit):
    with db_lock:
        touch_user(user_id)
        conn = get_conn()
        conn.execute("UPDATE users SET base_daily_limit = ? WHERE user_id = ?", (max(0, int(new_limit)), str(user_id)))
        conn.commit()
        
        c = conn.cursor()
        c.execute("SELECT base_daily_limit FROM users WHERE user_id = ?", (str(user_id),))
        lim = c.fetchone()["base_daily_limit"]
        conn.close()
        return True, lim

def add_user_bonus_generations(user_id, count):
    with db_lock:
        touch_user(user_id)
        conn = get_conn()
        c = conn.cursor()
        if count == "reset":
            c.execute("UPDATE users SET bonus_credits = 0 WHERE user_id = ?", (str(user_id),))
        else:
            c.execute("UPDATE users SET bonus_credits = MAX(0, bonus_credits + ?) WHERE user_id = ?", (int(count), str(user_id)))
        conn.commit()
        
        c.execute("SELECT bonus_credits FROM users WHERE user_id = ?", (str(user_id),))
        cred = c.fetchone()["bonus_credits"]
        conn.close()
        return True, cred

def reset_user_daily_count(user_id):
    with db_lock:
        touch_user(user_id)
        conn = get_conn()
        conn.execute("UPDATE users SET daily_count = 0 WHERE user_id = ?", (str(user_id),))
        conn.commit()
        conn.close()
        return True

def reset_all_users_daily_limits_async(token, admin_chat_id, send_message_func):
    def _worker():
        today = datetime.now().strftime("%Y-%m-%d")
        reset_count = 0
        notified_count = 0
        target_uids = []

        with db_lock:
            conn = get_conn()
            c = conn.cursor()
            
            c.execute("SELECT user_id, username, base_daily_limit FROM users")
            all_users = c.fetchall()
            
            c.execute("UPDATE users SET daily_count = 0, daily_date = ?", (today,))
            conn.commit()
            conn.close()
            
            for row in all_users:
                uid = row["user_id"]
                reset_count += 1
                if not is_admin(uid, row["username"]) and str(uid) != str(admin_chat_id):
                    target_uids.append((uid, row["base_daily_limit"]))

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
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (q,))
    row = c.fetchone()
    if row:
        conn.close()
        return q, dict(row)
        
    c.execute("SELECT * FROM users WHERE LOWER(username) = ?", (q,))
    row = c.fetchone()
    if row:
        conn.close()
        return row["user_id"], dict(row)
        
    c.execute("SELECT * FROM users WHERE LOWER(username) LIKE ?", (f"%{q}%",))
    row = c.fetchone()
    if row:
        conn.close()
        return row["user_id"], dict(row)
        
    c.execute("SELECT * FROM users WHERE LOWER(first_name) LIKE ?", (f"%{q}%",))
    row = c.fetchone()
    if row:
        conn.close()
        return row["user_id"], dict(row)
        
    conn.close()
    return None, None

def log_generation(user_id, username, first_name, mode, char_name, pose_name, env_name, resolution, prompt, elapsed, is_custom=False, image_path="", img_id=None):
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute('''
        INSERT INTO history (
            id, time, user_id, username, first_name, mode, char, pose, env, res, prompt, elapsed, is_custom, image_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            img_id or uuid.uuid4().hex[:8], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(user_id), username or "без юзернейма", first_name or "", mode, char_name, pose_name,
            env_name, resolution, prompt, elapsed, is_custom, image_path
        ))
        
        # Limit history to 200 items by deleting the oldest ones
        c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY time DESC LIMIT 200)")
        
        conn.commit()
        conn.close()

def log_message(user_id, username, text):
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute('''
        INSERT INTO messages (time, user_id, username, text) VALUES (?, ?, ?, ?)
        ''', (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(user_id), username or "без юзернейма", text
        ))
        
        # Limit messages to 100 items
        c.execute("DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 100)")
        
        conn.commit()
        conn.close()

def add_pc_notify(chat_id):
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO pc_notifies (chat_id) VALUES (?)", (str(chat_id),))
        conn.commit()
        conn.close()

def get_pc_notifies():
    with db_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT chat_id FROM pc_notifies")
        notifies = [row["chat_id"] for row in c.fetchall()]
        conn.close()
        return notifies

def clear_pc_notifies():
    with db_lock:
        conn = get_conn()
        conn.execute("DELETE FROM pc_notifies")
        conn.commit()
        conn.close()
