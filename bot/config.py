import os
import json
import re
import copy
import threading
import queue
import sqlite3

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_DIR = os.path.join(APP_DIR, "bot")
CONFIG_PATH = os.path.join(APP_DIR, "tg_config.json")
DB_PATH = os.path.join(APP_DIR, "bot_database.json")
DB_SQLITE_PATH = os.path.join(APP_DIR, "bot_database.db")
HISTORY_DIR = os.path.join(APP_DIR, "history_images")
RELOAD_FLAG_PATH = os.path.join(APP_DIR, "reload_bot.flag")
STOP_FLAG_PATH = os.path.join(APP_DIR, "stop_bot.flag")
RESTART_NOTIFY_PATH = os.path.join(APP_DIR, "restart_notify.json")
API_URL = "http://127.0.0.1:7860/sdapi/v1/txt2img"
MAX_HISTORY_IMAGES = 200

os.makedirs(HISTORY_DIR, exist_ok=True)

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"bot_token": "", "chat_id": "", "admin_username": "", "interval_seconds": 120}

def get_admin_chat_id():
    return str(load_config().get("chat_id", "")).strip()

def get_admin_username():
    return str(load_config().get("admin_username", "")).strip().lstrip("@").lower()

_initial_cfg = load_config()
OMNIROUTE_URL = "http://127.0.0.1:20128/v1/chat/completions"
OMNIROUTE_KEY = os.environ.get("OMNIROUTE_KEY") or _initial_cfg.get("omniroute_key", "")
OMNIROUTE_TEXT_MODEL = "gweb/gemini-3.7-flash"
OMNIROUTE_VISION_MODEL = "gweb/gemini-3.7-flash"

AVAILABLE_MODELS = {
    "noobai": {
        "id": "noobai",
        "name": "NoobAI XL",
        "full_name": "NoobAI XL (V-Pred)",
        "checkpoint": "NoobAI-XL-Vpred-v1.0.safetensors",
        "lora_name": "gummyflux",
        "lora_weight": 0.95,
        "style_prefix": "gummyflux, cstyle",
        "description": "Danbooru/e621 стиль, сочный глянец и чистые цвета"
    },
    "illustrious": {
        "id": "illustrious",
        "name": "Illustrious XL",
        "full_name": "Illustrious XL (v0.1)",
        "checkpoint": "Illustrious-XL-v0.1.safetensors",
        "lora_name": "artist_style_lora",
        "lora_weight": 0.85,
        "style_prefix": "cstyle, glossy skin, sticker outline",
        "description": "Чистая 2D графика, стикерный контур и аккуратные лица"
    }
}
DEFAULT_MODEL = "noobai"
DEFAULT_CFG_SCALE = 5.0

db_lock = threading.RLock()
active_lock = threading.Lock()
gpu_lock = threading.Lock()
is_restarting_lock = threading.Lock()
is_restarting = False
is_shutting_down_lock = threading.Lock()
is_shutting_down = False

active_generations = set()
sessions = {}
generation_queue = queue.Queue()

CLOTHING_WORDS = [
    'clothes', 'clothing', 'outfit', 'costume', 'suit', 'dress', 'skirt',
    'shirt', 't-shirt', 'pants', 'shorts', 'bra', 'panties', 'underwear',
    'swimsuit', 'bikini', 'leotard', 'bodysuit', 'uniform', 'coat', 'jacket',
    'robe', 'sweater', 'blouse', 'jeans', 'apron', 'corset',
    'tights', 'leggings', 'stockings', 'socks', 'gloves', 'boots', 'fabric',
    'topwear', 'bottomwear', 'swimwear', 'headband', 'hoodie', 'vest',
    'cape', 'cloak', 'scarf', 'veil', 'thong', 'boxers', 'briefs',
    'bloomers', 'pasties', 'maid', 'kimono', 'yukata', 'lingerie',
    'pajamas', 'nightgown', 'cardigan', 'shoes', 'sneakers', 'sandals',
    'heels', 'loafers', 'slippers', 'overalls', 'sleeves',
    'suspenders', 'tank top', 'crop top', 'tube top', 'halterneck', 'choker', 'collar', 'tie', 'bowtie'
]
CLOTHING_RE = re.compile(r'\b(' + '|'.join(re.escape(w) for w in CLOTHING_WORDS) + r')\b', re.IGNORECASE)

DEFAULT_CHARS_FEMALE = [
    ("Tifa Lockhart", "1girl, solo, tifa lockhart, dark hair, red eyes, large breasts, athletic, white tank top, suspenders"),
    ("2B (Nier:Automata)", "1girl, solo, 2b \(nier:automata\), blindfold, white hair, goth dress, sword"),
    ("Ahri (League of Legends)", "1girl, solo, ahri, nine tails, fox ears, blue eyes, curvy, magical orb"),
    ("Raiden Shogun", "1girl, solo, raiden shogun, purple hair, braid, purple eyes, ornate kimono, divine"),
    ("Power (Chainsaw Man)", "1girl, solo, power \(chainsaw man\), blonde hair, horns, sharp teeth, casual jacket"),
    ("Makima", "1girl, solo, makima \(chainsaw man\), red hair, braided hair, yellow eyes with rings, white shirt, tie"),
    ("Rem (Re:Zero)", "1girl, solo, rem \(re:zero\), blue hair, short hair, maid outfit, one eye covered"),
    ("Loona (Helluva Boss)", "1girl, solo, loona \(helluva boss\), anthropomorphic wolf, wolf girl, grey fur, red eyes, goth clothes")
]

DEFAULT_CHARS_MALE = [
    ("Homdan (Minecraft)", "1boy, solo, homdan \(minecraft\), dark skin, dark-skinned male, bear ears, animal ears, brown hair, short hair, curly hair, mouth mask, blue hoodie"),
    ("Gojo Satoru (JJK)", "1boy, solo, gojo satoru, blindfold, white hair, spiky hair, tall, handsome, dark blue jacket"),
    ("Cloud Strife (FF7)", "1boy, solo, cloud strife, blonde hair, spiky hair, blue eyes, athletic, shoulder armor, black turtleneck"),
    ("Zoro (One Piece)", "1boy, solo, roronoa zoro, green hair, short hair, scar on eye, muscular, three earrings, green haramaki"),
    ("Dante (DMC)", "1boy, solo, dante \(devil may cry\), white hair, red coat, athletic, handsome, stubble")
]

DEFAULT_CHARS = DEFAULT_CHARS_FEMALE

DEFAULT_POSES_SFW = [
    ("Standing (Hand on Hip)", "standing, hand on hip, looking at viewer"),
    ("Sitting", "sitting, looking at viewer, relaxed posture"),
    ("Waving", "waving at viewer, cheerful, dynamic pose, smiling"),
    ("Leaning Forward", "leaning forward, resting arms, upper body shot"),
    ("Peace Sign", "peace sign, v sign, wink, playful, cute pose"),
    ("Arms Crossed", "crossed arms, confident expression, stylish stance"),
    ("Looking Over Shoulder", "looking back, looking over shoulder, turn around"),
    ("Sitting on Chair", "sitting on wooden chair, relaxed legs, gentle smile"),
    ("Walking", "walking towards viewer, dynamic movement, windy hair"),
    ("Hands Behind Back", "hands behind back, leaning slightly forward, cute smile"),
    ("Adjusting Hair", "adjusting hair, touching own hair, side glance"),
    ("Stretching", "stretching arms overhead, relaxed, morning vibe")
]

DEFAULT_POSES_NSFW = [
    ("All Fours (Doggystyle)", "all fours, on all fours, arched back, looking back at viewer, ass focus"),
    ("Kneeling Seductive", "kneeling, looking up at viewer, parted lips, seductive expression, spread thighs"),
    ("Lying on Stomach", "lying on stomach, arched back, looking back, feet up, bare soles"),
    ("Lying on Back (Legs Spread)", "lying on back, spread legs, knees up, blushing, hands on chest"),
    ("Bent Over", "bent over, ass focus, looking back over shoulder, tempting pose"),
    ("Cowgirl Stance", "straddling, knees apart, leaning back, flushed face, seductive"),
    ("Presenting Ass", "presenting, bent over, ass, looking back at viewer, blushing"),
    ("Hands Tied / Bound", "hands tied behind back, kneeling, submissive, blushing, looking away"),
    ("Jack-o Challenge", "jack-o' challenge, crouch, ass up, looking back, flexible"),
    ("Sitting Legs Apart", "sitting, legs spread, leaning back on hands, inviting posture"),
    ("Doggystyle (From Behind)", "doggystyle, from behind, sex from behind, arched back, on all fours, penetration"),
    ("Missionary (Lying on Back)", "missionary, lying on back, legs up, spread legs, sex, penetration"),
    ("Cowgirl / Riding", "cowgirl position, straddling, riding, on top, bounce, sex, penetration"),
    ("Mating Press", "mating press, legs over head, folded, close up, missionary, sex"),
    ("Oral / Fellatio", "fellatio, oral, kneeling, sucking, penis in mouth, looking up, blush"),
    ("Paizuri / Titfuck", "paizuri, breast hold, penis between breasts, cleavage")
]

DEFAULT_POSES = DEFAULT_POSES_SFW + DEFAULT_POSES_NSFW

DEFAULT_ENVS = [
    ("Ruins (Undertale)", "ruins \(undertale\), ancient stone hall, sunbeams"),
    ("Cyberpunk City", "cyberpunk city, neon lights, rainy street, night, reflections"),
    ("Cozy Bedroom", "cozy bedroom, messy bed, warm lighting, posters on wall"),
    ("Mystical Forest", "mystical forest, glowing mushrooms, fairy lights, magical atmosphere"),
    ("Hot Springs / Onsen", "onsen, hot springs, outdoor bath, steam, rocks, bamboo"),
    ("Beach Sunset", "tropical beach, sunset, golden hour, ocean waves, palms"),
    ("Gothic Castle", "gothic castle, dark hall, stained glass, candlelight, velvet curtains"),
    ("Classroom", "anime classroom, desks, blackboard, sunlight through window, evening"),
    ("Rooftop at Sunset", "city rooftop, sunset sky, fence, skyscrapers in background, clouds"),
    ("Shower / Bathroom", "modern bathroom, glass shower, mist, wet tiles, soft lighting"),
    ("Luxury Hotel Bed", "luxury hotel room, silk sheets, plush pillows, panoramic window city view"),
    ("Fantasy Dungeon", "dungeon, stone walls, iron bars, torches, moody shadows"),
    ("Cherry Blossom Park", "sakura garden, cherry blossom trees, falling petals, bench, spring"),
    ("Futuristic Laboratory", "sci-fi laboratory, holographic screens, glowing neon tubes, clean room"),
    ("Coffee Shop / Cafe", "cozy cafe interior, wooden tables, warm atmosphere, plants, window")
]

STARS_PACKAGES = {
    "1": {"count": 1, "stars": 2, "discount": 0, "title": "1 генерация (2 Stars)", "btn": "⭐️ 1 арт — 2 Stars"},
    "5": {"count": 5, "stars": 8, "discount": 20, "title": "5 генераций (-20%) (8 Stars)", "btn": "🔥 5 артов — 8 Stars (-20%)"},
    "15": {"count": 15, "stars": 20, "discount": 33, "title": "15 генераций (-33%) (20 Stars)", "btn": "💎 15 артов — 20 Stars (-33%)"},
    "50": {"count": 50, "stars": 55, "discount": 45, "title": "50 генераций (-45%) (55 Stars)", "btn": "🚀 50 артов — 55 Stars (-45%)"},
    "100": {"count": 100, "stars": 99, "discount": 50, "title": "100 генераций (-50%) (99 Stars)", "btn": "👑 100 артов — 99 Stars (-50%)"}
}

BOT_USERNAME = "GpuMonitor2_bot"
SESSIONS_PATH = os.path.join(APP_DIR, "bot_sessions.json")
sessions_loaded = False
sessions_lock = threading.Lock()

def save_sessions():
    with sessions_lock:
        try:
            conn = sqlite3.connect(DB_SQLITE_PATH, timeout=10)
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS sessions (chat_id TEXT PRIMARY KEY, data TEXT)')
            
            for k, v in sessions.items():
                c.execute('INSERT OR REPLACE INTO sessions (chat_id, data) VALUES (?, ?)', (str(k), json.dumps(v, ensure_ascii=False)))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving sessions to SQLite: {e}", flush=True)

def _load_persisted_sessions():
    global sessions_loaded
    try:
        conn = sqlite3.connect(DB_SQLITE_PATH, timeout=10)
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS sessions (chat_id TEXT PRIMARY KEY, data TEXT)')
        
        c.execute('SELECT chat_id, data FROM sessions')
        rows = c.fetchall()
        if rows:
            for row in rows:
                k = row[0]
                v = json.loads(row[1])
                v["state"] = "idle"
                sessions[k] = v
        else:
            # Fallback to json if sqlite is empty (migration)
            if os.path.exists(SESSIONS_PATH):
                with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if isinstance(saved, dict):
                        for k, v in saved.items():
                            v["state"] = "idle"
                            sessions[k] = v
                            c.execute('INSERT OR REPLACE INTO sessions (chat_id, data) VALUES (?, ?)', (str(k), json.dumps(v, ensure_ascii=False)))
                conn.commit()
        
        conn.close()
    except Exception as e:
        print(f"Error loading sessions: {e}", flush=True)
    sessions_loaded = True

def get_session(chat_id):
    import random
    global sessions_loaded
    with sessions_lock:
        if not sessions_loaded:
            _load_persisted_sessions()
        cid = str(chat_id)
        if cid not in sessions:
            char = random.choice(DEFAULT_CHARS)
            pose = random.choice(DEFAULT_POSES)
            env = random.choice(DEFAULT_ENVS)
            sessions[cid] = {
                "char_name": char[0],
                "char_prompt": char[1],
                "char_gender": "female",
                "pose_name": pose[0],
                "pose_prompt": pose[1],
                "env_name": env[0],
                "env_prompt": env[1],
                "width": 832,
                "height": 1216,
                "mode": "nsfw",
                "partner_mode": "none",
                "model": DEFAULT_MODEL,
                "state": "idle",
                "steps": 28,
                "cfg_scale": DEFAULT_CFG_SCALE,
                "search_target": None,
                "target_user_id": None,
                "last_is_custom": False,
                "last_custom_prompt": ""
            }
        if "char_gender" not in sessions[cid]:
            p_low = sessions[cid].get("char_prompt", "").lower()
            sessions[cid]["char_gender"] = "male" if any(k in p_low for k in ["1boy", "1man", "homdan", "male"]) and "1girl" not in p_low else "female"
        if "partner_mode" not in sessions[cid]:
            sessions[cid]["partner_mode"] = "none"
        if "cfg_scale" not in sessions[cid]:
            sessions[cid]["cfg_scale"] = DEFAULT_CFG_SCALE
        else:
            try:
                sessions[cid]["cfg_scale"] = round(min(max(1.0, float(sessions[cid]["cfg_scale"])), 15.0), 1)
            except Exception:
                sessions[cid]["cfg_scale"] = DEFAULT_CFG_SCALE
        if "model" not in sessions[cid] or sessions[cid]["model"] not in AVAILABLE_MODELS:
            sessions[cid]["model"] = DEFAULT_MODEL
        return sessions[cid]
