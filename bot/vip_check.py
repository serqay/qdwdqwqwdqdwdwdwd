import time
from bot.database import get_conn

def check_is_vip(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT vip_until FROM users WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    if row and row['vip_until']:
        return True # Simplified for now
    return False
