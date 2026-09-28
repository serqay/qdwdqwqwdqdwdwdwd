import os
import html
import urllib.parse
from datetime import datetime
from bot.config import (
    active_generations, active_lock, STARS_PACKAGES, DEFAULT_CHARS,
    DEFAULT_CHARS_FEMALE, DEFAULT_CHARS_MALE,
    DEFAULT_POSES, DEFAULT_ENVS, BOT_USERNAME, AVAILABLE_MODELS, DEFAULT_MODEL,
    DEFAULT_CFG_SCALE
)
from bot.database import load_db, get_user_limits_status, is_admin, get_user_referral_stats

def render_buy_stars_menu():
    text = (
        "⭐️ <b>МАГАЗИН ДОПОЛНИТЕЛЬНЫХ ГЕНЕРАЦИЙ</b>\n\n"
        "Купленные генерации действуют бессрочно, не сгорают в полночь и расходуются после исчерпания суточного лимита.\n\n"
        "Выберите пакет со скидкой:\n"
        "• <b>1 арт</b> — 2 ⭐️ Stars <i>(2.0 ⭐️/арт)</i>\n"
        "• <b>5 артов</b> — 8 ⭐️ Stars <i>(скидка 20%, 1.6 ⭐️/арт)</i>\n"
        "• <b>15 артов</b> — 20 ⭐️ Stars <i>(скидка 33%, 1.3 ⭐️/арт)</i>\n"
        "• <b>50 артов</b> — 55 ⭐️ Stars <i>(скидка 45%, 1.1 ⭐️/арт)</i>\n"
        "• <b>100 артов</b> — 99 ⭐️ Stars <i>(скидка 50%, ~1.0 ⭐️/арт)</i>"
    )
    kb = [
        [{"text": "⭐️ 1 арт — 2 Stars", "callback_data": "buy_pkg_1"}],
        [{"text": "🔥 5 артов — 8 Stars (-20%)", "callback_data": "buy_pkg_5"}],
        [{"text": "💎 15 артов — 20 Stars (-33%)", "callback_data": "buy_pkg_15"}],
        [{"text": "🚀 50 артов — 55 Stars (-45%)", "callback_data": "buy_pkg_50"}],
        [{"text": "👑 100 артов — 99 Stars (-50%)", "callback_data": "buy_pkg_100"}],
        [{"text": "◀️ Назад в главное меню", "callback_data": "menu_main"}]
    ]
    return text, {"inline_keyboard": kb}

def make_referral_menu(user_id, bot_username=None):
    b_name = bot_username or BOT_USERNAME
    ref_count, bonus_earned = get_user_referral_stats(user_id)
    ref_link = f"https://t.me/{b_name}?start=ref_{user_id}"
    share_text = urllib.parse.quote("Попробуй нейросеть GummyFlux для создания качественных аниме артов без ограничений! По ссылке дают +1 стартовый бонус:")
    share_url = f"https://t.me/share/url?url={ref_link}&text={share_text}"

    text = (
        "🎁 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n\n"
        "Приглашайте друзей и получайте бесплатные генерации без ограничений по времени!\n\n"
        "• <b>Вы получаете:</b> +2 бонусных генерации за каждого друга\n"
        "• <b>Ваш друг получает:</b> +1 приветственную генерацию сразу на баланс\n\n"
        f"📊 <b>Ваша статистика:</b>\n"
        f"• Приглашено друзей: <b>{ref_count}</b>\n"
        f"• Заработано генераций: <b>+{bonus_earned}</b>\n\n"
        f"🔗 <b>Ваша персональная ссылка:</b>\n<code>{ref_link}</code>\n\n"
        "<i>Нажмите кнопку «Поделиться ссылкой», чтобы отправить приглашение в любой чат Telegram:</i>"
    )

    kb = [
        [{"text": "📤 Поделиться ссылкой", "url": share_url}],
        [{"text": "◀️ Назад в главное меню", "callback_data": "menu_main"}]
    ]
    return text, {"inline_keyboard": kb}

def make_main_menu(session, user_id=None, username=None):
    char_name = html.escape(str(session.get("char_name", "Не выбран")))
    char_gender = session.get("char_gender", "female")
    gender_badge = "👩 Женский" if char_gender == "female" else "👨 Мужской"
    pose_name = html.escape(str(session.get("pose_name", "Стандартная")))
    env_name = html.escape(str(session.get("env_name", "Без окружения")))
    width = session.get("width", 832)
    height = session.get("height", 1216)
    mode_text = "👗 В одежде (SFW)" if session.get("mode") == "sfw" else "🔥 Без одежды (NSFW)"
    partner_mode = session.get("partner_mode", "none")
    partner_info = " | 🔥 +Партнер (1boy)" if partner_mode == "with_male" else ""

    admin_flag, free_left, bonus_left, total_left = get_user_limits_status(user_id, username)
    if admin_flag:
        limit_text = "Безлимитный доступ (Администратор)"
    else:
        db = load_db()
        base_lim = db.get("users", {}).get(str(user_id), {}).get("base_daily_limit", 3) if user_id else 3
        if bonus_left > 0:
            limit_text = f"{free_left} из {base_lim} (+{bonus_left} бонусных/купленных)"
        else:
            limit_text = f"{free_left} из {base_lim}"

    text = (
        "<b>ПАНЕЛЬ УПРАВЛЕНИЯ GUMMYFLUX</b>\n\n"
        f"👤 <b>Персонаж:</b> {char_name} <i>({gender_badge})</i>\n"
        f"💃 <b>Поза:</b> {pose_name}\n"
        f"🏞 <b>Окружение:</b> {env_name}\n"
        f"⚙️ <b>Параметры:</b> {width}x{height} | {mode_text}{partner_info}\n"
        f"📊 <b>Лимит:</b> {limit_text}\n\n"
        "<i>Выберите категорию настроек или действие ниже:</i>"
    )

    kb = [
        [{"text": "🚀 [СГЕНЕРИРОВАТЬ АРТ]", "callback_data": "action_generate"}],
        [{"text": f"🔄 Режим: {mode_text}", "callback_data": "main_toggle_mode"}],
        [{"text": "👤 Персонаж", "callback_data": "menu_char"},
         {"text": "💃 Поза", "callback_data": "menu_pose"}],
        [{"text": "🏞 Окружение", "callback_data": "menu_env"},
         {"text": "⚙️ Настройки", "callback_data": "menu_settings"}],
        [{"text": "✍️ Свой кастомный промт", "callback_data": "menu_custom_prompt"},
         {"text": "⭐️ Купить генерации", "callback_data": "action_buy_stars"}],
        [{"text": "🎁 Пригласить друга (+2 арта)", "callback_data": "menu_referral"}]
    ]

    if is_admin(user_id, username):
        kb.append([{"text": "👑 Панель администратора", "callback_data": "admin_main"}])

    return text, {"inline_keyboard": kb}

def make_char_menu(session):
    char_name = html.escape(str(session.get("char_name", "Не выбран")))
    char_gender = session.get("char_gender", "female")
    gender_badge = "👩 Женский" if char_gender == "female" else "👨 Мужской"
    gender_toggle_btn = "👩 Пол: Женский (переключить на 👨)" if char_gender == "female" else "👨 Пол: Мужской (переключить на 👩)"
    char_prompt = session.get("char_prompt", "")
    short_prompt = char_prompt[:90] + "..." if len(char_prompt) > 90 else char_prompt
    short_prompt_esc = html.escape(short_prompt)
    
    text = (
        "👤 <b>УПРАВЛЕНИЕ ПЕРСОНАЖЕМ</b>\n\n"
        f"Текущий персонаж: <b>{char_name}</b> <i>({gender_badge})</i>\n"
        f"Теги: <code>{short_prompt_esc}</code>\n\n"
        "Выберите действие через ИИ, поиск онлайн или популярного персонажа:"
    )
    kb = [
        [{"text": f"🔄 {gender_toggle_btn}", "callback_data": "action_toggle_char_gender"}],
        [{"text": "✨ Описать через ИИ", "callback_data": "start_ai_describe_char"},
         {"text": "📸 Персонаж по фото (ИИ)", "callback_data": "start_char_photo"}],
        [{"text": "🔍 Поиск персонажа онлайн", "callback_data": "start_search_char"},
         {"text": "🎲 Случайный персонаж", "callback_data": "char_random"}]
    ]
    if char_gender == "male":
        kb.extend([
            [{"text": "Homdan (Minecraft)", "callback_data": "preset_char_male_0"},
             {"text": "Gojo Satoru (JJK)", "callback_data": "preset_char_male_1"}],
            [{"text": "Cloud Strife (FF7)", "callback_data": "preset_char_male_2"},
             {"text": "Zoro (One Piece)", "callback_data": "preset_char_male_3"}],
            [{"text": "Dante (DMC)", "callback_data": "preset_char_male_4"}]
        ])
    else:
        kb.extend([
            [{"text": "2B (NieR)", "callback_data": "preset_char_fem_1"},
             {"text": "Tifa Lockhart", "callback_data": "preset_char_fem_0"}],
            [{"text": "Ahri (LoL)", "callback_data": "preset_char_fem_2"},
             {"text": "Raiden Shogun", "callback_data": "preset_char_fem_3"}],
            [{"text": "Power (CSM)", "callback_data": "preset_char_fem_4"},
             {"text": "Makima", "callback_data": "preset_char_fem_5"}],
            [{"text": "Rem (Re:Zero)", "callback_data": "preset_char_fem_6"},
             {"text": "Loona (Helluva)", "callback_data": "preset_char_fem_7"}]
        ])
    kb.append([{"text": "◀️ Назад в меню", "callback_data": "menu_main"}])
    return text, {"inline_keyboard": kb}

def make_pose_menu(session):
    pose_name = html.escape(str(session.get("pose_name", "Стандартная")))
    pose_prompt = session.get("pose_prompt", "")
    short_prompt = pose_prompt[:90] + "..." if len(pose_prompt) > 90 else pose_prompt
    short_prompt_esc = html.escape(short_prompt)
    
    text = (
        "💃 <b>ВЫБОР ПОЗЫ</b>\n\n"
        f"Текущая поза: <b>{pose_name}</b>\n"
        f"Теги: <code>{short_prompt_esc}</code>\n\n"
        "Выберите действие или одну из популярных поз:"
    )
    kb = [
        [{"text": "✨ Случайная SFW поза", "callback_data": "pose_random_sfw"},
         {"text": "🔥 Случайная NSFW поза", "callback_data": "pose_random_nsfw"}],
        [{"text": "🔍 Поиск позы онлайн", "callback_data": "start_search_pose"},
         {"text": "🎲 Любая поза", "callback_data": "pose_random"}],
        [{"text": "🧍 Стоя (рука на бедре)", "callback_data": "preset_pose_0"},
         {"text": "🪑 Сидя", "callback_data": "preset_pose_1"}],
        [{"text": "👋 Приветствие (машет)", "callback_data": "preset_pose_2"},
         {"text": "🙇 Наклон вперед", "callback_data": "preset_pose_3"}],
        [{"text": "✌️ Знак мира (Peace)", "callback_data": "preset_pose_4"},
         {"text": "🙅 Скрестив руки", "callback_data": "preset_pose_5"}],
        [{"text": "◀️ Назад в меню", "callback_data": "menu_main"}]
    ]
    return text, {"inline_keyboard": kb}

def make_env_menu(session):
    env_name = html.escape(str(session.get("env_name", "Без окружения")))
    env_prompt = session.get("env_prompt", "")
    short_prompt = env_prompt[:90] + "..." if len(env_prompt) > 90 else (env_prompt or "без тегов")
    short_prompt_esc = html.escape(short_prompt)
    
    text = (
        "🏞 <b>ВЫБОР ОКРУЖЕНИЯ И ФОНА</b>\n\n"
        f"Текущий фон: <b>{env_name}</b>\n"
        f"Теги: <code>{short_prompt_esc}</code>\n\n"
        "Выберите поиск онлайн или популярную локацию:"
    )
    kb = [
        [{"text": "🎲 Случайная локация", "callback_data": "env_random"},
         {"text": "🔍 Поиск онлайн", "callback_data": "start_search_env"}],
        [{"text": "❌ Без окружения (Очистить)", "callback_data": "clear_env"}],
        [{"text": "🌆 Киберпанк город", "callback_data": "preset_env_1"},
         {"text": "🛏 Уютная спальня", "callback_data": "preset_env_2"}],
        [{"text": "🌲 Волшебный лес", "callback_data": "preset_env_3"},
         {"text": "🏖 Закат на пляже", "callback_data": "preset_env_5"}],
        [{"text": "🏰 Готический замок", "callback_data": "preset_env_6"},
         {"text": "♨️ Горячие источники", "callback_data": "preset_env_4"}],
        [{"text": "🏛 Древние руины", "callback_data": "preset_env_0"},
         {"text": "🏫 Аниме класс", "callback_data": "preset_env_7"}],
        [{"text": "◀️ Назад в меню", "callback_data": "menu_main"}]
    ]
    return text, {"inline_keyboard": kb}

def make_settings_menu(session, user_id=None, username=None):
    w = session.get("width", 832)
    h = session.get("height", 1216)
    mode = session.get("mode", "nsfw")
    mode_text = "👗 В одежде (SFW)" if mode == "sfw" else "🔥 Без одежды (Uncensored / NSFW)"
    toggle_text = "Сделать в одежде (SFW)" if mode == "nsfw" else "Сделать без одежды (NSFW)"

    cur_model_id = session.get("model", DEFAULT_MODEL)
    cur_model = AVAILABLE_MODELS.get(cur_model_id, AVAILABLE_MODELS.get(DEFAULT_MODEL))
    model_name = cur_model["name"]
    model_full_name = html.escape(str(cur_model["full_name"]))

    steps = int(session.get("steps", 20))
    admin_mode = is_admin(user_id, username)
    if not admin_mode:
        steps = max(15, min(25, steps))

    partner_mode = session.get("partner_mode", "none")
    partner_status = "🔥 Включен (1boy + член)" if partner_mode == "with_male" else "👤 Выключен (Соло)"
    partner_btn = "👤 Убрать партнера (Соло)" if partner_mode == "with_male" else "🔥 Добавить партнера (1boy + член)"
    char_gender = session.get("char_gender", "female")
    gender_info = "👩 Женский" if char_gender == "female" else "👨 Мужской"
    gender_btn = "👨 Сменить пол на Мужской" if char_gender == "female" else "👩 Сменить пол на Женский"

    cfg_scale = float(session.get("cfg_scale", DEFAULT_CFG_SCALE))
    cfg_scale = round(min(max(1.0, cfg_scale), 15.0), 1)

    text = (
        "⚙️ <b>НАСТРОЙКИ ГЕНЕРАЦИИ</b>\n\n"
        f"• Пол персонажа: <b>{gender_info}</b>\n"
        f"• Модель нейросети: <b>{model_full_name}</b>\n"
        f"• Следование промту (CFG): <b>{cfg_scale}</b> (от 1.0 до 15.0)\n"
        f"• Шаги семплирования (Samples): <b>{steps}</b>\n"
        f"• Текущее разрешение: <b>{w}x{h}</b>\n"
        f"• Режим внешности: <b>{mode_text}</b>\n"
        f"• Мужской партнер (18+): <b>{partner_status}</b>\n\n"
        "Выберите параметр для изменения:"
    )
    kb = [
        [{"text": f"🚻 {gender_btn}", "callback_data": "settings_toggle_char_gender"}],
        [{"text": f"🧠 Модель: {model_name}", "callback_data": "menu_models"},
         {"text": f"🎯 Сила промта (CFG): {cfg_scale}", "callback_data": "menu_cfg"}],
        [{"text": f"⚡ Шаги (Samples): {steps}", "callback_data": "menu_samples"},
         {"text": f"📐 Разрешение: {w}x{h}", "callback_data": "menu_resolution"}],
        [{"text": f"🔄 {toggle_text}", "callback_data": "action_toggle_mode"}],
        [{"text": f"👥 {partner_btn}", "callback_data": "action_toggle_partner"}],
        [{"text": "◀️ Назад в главное меню", "callback_data": "menu_main"}]
    ]
    return text, {"inline_keyboard": kb}

def make_cfg_menu(session):
    cur_cfg = float(session.get("cfg_scale", DEFAULT_CFG_SCALE))
    cur_cfg = round(min(max(1.0, cur_cfg), 15.0), 1)

    text = (
        "🎯 <b>СИЛА СЛЕДОВАНИЯ ПРОМПТУ (CFG SCALE)</b>\n\n"
        "Параметр <b>CFG Scale</b> (соблюдение правил промпта) определяет, насколько строго нейросеть придерживается описания:\n\n"
        "• <b>1.0 – 3.5:</b> Мягкое/свободное следование, творческая свобода нейросети, мягкие пастельные тона.\n"
        "• <b>4.0 – 6.5:</b> Оптимальный баланс для аниме-моделей (стандарт <b>5.5</b>). Точное сходство с персонажем и естественный контраст.\n"
        "• <b>7.0 – 10.0:</b> Строгое исполнение каждого тега, повышенная резкость и насыщенность.\n"
        "• <b>10.5 – 15.0:</b> Предельное соблюдение всех правил промта (максимум до 15.0).\n\n"
        f"Текущее значение: <b>{cur_cfg}</b>"
    )

    prev_val = round(max(1.0, cur_cfg - 0.5), 1)
    next_val = round(min(15.0, cur_cfg + 0.5), 1)

    kb = [
        [
            {"text": f"➖ 0.5 ({prev_val})", "callback_data": f"set_cfg_{prev_val}"},
            {"text": f"➕ 0.5 ({next_val})", "callback_data": f"set_cfg_{next_val}"}
        ],
        [
            {"text": "1.0", "callback_data": "set_cfg_1.0"},
            {"text": "3.5", "callback_data": "set_cfg_3.5"},
            {"text": "5.5 (База)", "callback_data": "set_cfg_5.5"},
            {"text": "7.0", "callback_data": "set_cfg_7.0"},
            {"text": "10.0", "callback_data": "set_cfg_10.0"},
            {"text": "15.0", "callback_data": "set_cfg_15.0"}
        ],
        [{"text": "✍️ Ввести точное число (от 1.0 до 15.0)", "callback_data": "start_custom_cfg"}],
        [{"text": "◀️ Назад в настройки", "callback_data": "menu_settings"}]
    ]
    return text, {"inline_keyboard": kb}

def make_models_menu(session):
    cur_model_id = session.get("model", DEFAULT_MODEL)
    text = (
        "🧠 <b>ВЫБОР МОДЕЛИ НЕЙРОСЕТИ</b>\n\n"
        "Выберите базовую модель для генерации артов:\n\n"
        "• <b>NoobAI XL (V-Pred)</b> — высокая детализация, анатомическая точность, глубокое знание стилей и тегов Danbooru/e621.\n"
        "• <b>Illustrious XL (v0.1)</b> — чистый 2D/аниме стиль, аккуратная прорисовка лиц, яркие цвета и стабильные композиции.\n\n"
        f"Текущая модель: <b>{AVAILABLE_MODELS.get(cur_model_id, {}).get('full_name', 'NoobAI XL')}</b>"
    )
    kb = [
        [{"text": f"{'✅ ' if cur_model_id == 'noobai' else ''}🎨 NoobAI XL (V-Pred)", "callback_data": "set_model_noobai"}],
        [{"text": f"{'✅ ' if cur_model_id == 'illustrious' else ''}✨ Illustrious XL (v0.1)", "callback_data": "set_model_illustrious"}],
        [{"text": "◀️ Назад в настройки", "callback_data": "menu_settings"}]
    ]
    return text, {"inline_keyboard": kb}

def make_samples_menu(session, user_id=None, username=None):
    admin_mode = is_admin(user_id, username)
    steps = int(session.get("steps", 20))
    if not admin_mode:
        steps = max(15, min(25, steps))

    if admin_mode:
        text = (
            "⚡ <b>ШАГИ СЕМПЛИРОВАНИЯ (SAMPLES) — АДМИНИСТРАТОР</b>\n\n"
            f"Текущее значение: <b>{steps}</b> шагов.\n\n"
            "• <b>15 шагов</b> — быстрый рендер (~4 сек)\n"
            "• <b>20 шагов</b> — стандарт (~5 сек)\n"
            "• <b>25 шагов</b> — высокое качество (~7 сек)\n"
            "• <b>30 шагов</b> — глубокая проработка (~9 сек)\n"
            "• <b>40 шагов</b> — ультра-детализация\n\n"
            "Выберите пресет или введите нужное число (от 5 до 60):"
        )
        kb = [
            [{"text": f"{'✅ ' if steps == 15 else ''}15 (Быстро)", "callback_data": "set_samples_15"},
             {"text": f"{'✅ ' if steps == 20 else ''}20 (Стандарт)", "callback_data": "set_samples_20"},
             {"text": f"{'✅ ' if steps == 25 else ''}25 (Детально)", "callback_data": "set_samples_25"}],
            [{"text": f"{'✅ ' if steps == 30 else ''}30 (Качество)", "callback_data": "set_samples_30"},
             {"text": f"{'✅ ' if steps == 35 else ''}35 (Глубоко)", "callback_data": "set_samples_35"},
             {"text": f"{'✅ ' if steps == 40 else ''}40 (Экстрим)", "callback_data": "set_samples_40"}],
            [{"text": "⌨️ Ввести точное число (от 5 до 60)", "callback_data": "start_custom_samples"}],
            [{"text": "◀️ Назад в настройки", "callback_data": "menu_settings"}]
        ]
    else:
        text = (
            "⚡ <b>ШАГИ СЕМПЛИРОВАНИЯ (SAMPLES)</b>\n\n"
            f"Текущее значение: <b>{steps}</b> шагов.\n"
            "<i>(Для стандартных пользователей доступен диапазон от 15 до 25 шагов)</i>\n\n"
            "• <b>15 шагов</b> — быстрый рендер (~4 сек)\n"
            "• <b>20 шагов</b> — оптимальный баланс скорости и качества (~5 сек)\n"
            "• <b>25 шагов</b> — максимальная детализация (~7 сек)\n\n"
            "Выберите пресет или введите число от 15 до 25:"
        )
        kb = [
            [{"text": f"{'✅ ' if steps == 15 else ''}15 (Быстро)", "callback_data": "set_samples_15"},
             {"text": f"{'✅ ' if steps == 20 else ''}20 (Стандарт)", "callback_data": "set_samples_20"},
             {"text": f"{'✅ ' if steps == 25 else ''}25 (Максимум)", "callback_data": "set_samples_25"}],
            [{"text": "⌨️ Ввести число (от 15 до 25)", "callback_data": "start_custom_samples"}],
            [{"text": "◀️ Назад в настройки", "callback_data": "menu_settings"}]
        ]
    return text, {"inline_keyboard": kb}

def make_resolution_menu(session):
    w = session.get("width", 832)
    h = session.get("height", 1216)
    text = (
        "📐 <b>ВЫБОР РАЗРЕШЕНИЯ</b>\n\n"
        f"Текущий размер: <b>{w}x{h}</b>\n\n"
        "Выберите стандартный пресет или задайте точные размеры вручную (до 1500 пикселей):"
    )
    markup = {
        "inline_keyboard": [
            [{"text": "832x1216 (Вертикальный портрет)", "callback_data": "res_832_1216"}],
            [{"text": "1024x1024 (Квадрат 1:1)", "callback_data": "res_1024_1024"}],
            [{"text": "1216x832 (Горизонтальный пейзаж)", "callback_data": "res_1216_832"}],
            [{"text": "896x1344 (Высокий портрет)", "callback_data": "res_896_1344"}],
            [{"text": "1344x896 (Широкий формат)", "callback_data": "res_1344_896"}],
            [{"text": "768x1024 (Стандарт 3:4)", "callback_data": "res_768_1024"}],
            [{"text": "⌨️ Ввести свое разрешение вручную", "callback_data": "start_custom_res"}],
            [{"text": "◀️ Назад в настройки", "callback_data": "menu_settings"}]
        ]
    }
    return text, markup

def make_admin_menu():
    text = (
        "👑 <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\n\n"
        "Выберите раздел для управления ботом, лимитами пользователей и просмотра артов:"
    )
    markup = {
        "inline_keyboard": [
            [{"text": "📊 Общая статистика", "callback_data": "admin_stats"}],
            [{"text": "👥 Пользователи и лимиты", "callback_data": "admin_users_page_0"}],
            [{"text": "🔄 Сбросить лимиты ВСЕМ пользователям", "callback_data": "admin_confirm_reset_all_view"}],
            [{"text": "🔍 Найти пользователя по @username", "callback_data": "admin_search_user"}],
            [{"text": "🖼 История генераций и просмотр", "callback_data": "admin_hist_page_0"}],
            [{"text": "💬 Сообщения в чатах", "callback_data": "admin_messages"}],
            [{"text": "⚡ Шаги семплирования (Samples)", "callback_data": "menu_samples"}],
            [{"text": "🔄 Безопасное обновление бота (Hot Reload)", "callback_data": "admin_safe_restart"}],
            [{"text": "🛑 Выключить бота", "callback_data": "admin_confirm_shutdown"}],
            [{"text": "◀️ Вернуться в главное меню", "callback_data": "menu_main"}]
        ]
    }
    return text, markup

def render_admin_stats():
    db = load_db()
    users = db.get("users", {})
    history = db.get("history", [])

    total_users = len(users)
    today = datetime.now().strftime("%Y-%m-%d")

    active_today = 0
    gens_today = 0
    total_gens = 0
    total_stars = 0

    for u in users.values():
        if u.get("daily_date") == today and u.get("daily_count", 0) > 0:
            active_today += 1
            gens_today += u.get("daily_count", 0)
        total_gens += u.get("total_count", 0)
        total_stars += u.get("total_stars", 0)

    with active_lock:
        current_active = len(active_generations)

    text = (
        "📊 <b>СТАТИСТИКА БОТА</b>\n\n"
        f"Всего пользователей в базе: {total_users}\n"
        f"Активных сегодня: {active_today}\n"
        f"Генераций сегодня: {gens_today}\n"
        f"Всего генераций за все время: {total_gens}\n"
        f"Оплачено через Telegram Stars: {total_stars} ⭐️\n"
        f"Текущих генераций прямо сейчас: {current_active}\n"
        f"Всего записей в истории: {len(history)}"
    )
    markup = {
        "inline_keyboard": [
            [{"text": "🔄 Обновить", "callback_data": "admin_stats"}],
            [{"text": "◀️ Назад в админку", "callback_data": "admin_main"}]
        ]
    }
    return text, markup

def render_admin_users(page=0):
    db = load_db()
    users = db.get("users", {})
    sorted_users = sorted(users.values(), key=lambda x: x.get("last_seen", ""), reverse=True)
    today = datetime.now().strftime("%Y-%m-%d")

    per_page = 6
    total_pages = max(1, (len(sorted_users) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    page_users = sorted_users[page * per_page : (page + 1) * per_page]

    lines = [f"👥 <b>ПОЛЬЗОВАТЕЛИ БОТА (Стр. {page + 1}/{total_pages})</b>\nНажмите на пользователя для изменения лимитов:\n"]
    kb = []

    if not sorted_users:
        lines.append("Пока никто не пользовался ботом.")
    else:
        for idx, u in enumerate(page_users, page * per_page + 1):
            raw_uname = f"@{u.get('username')}" if u.get("username") else f"ID {u.get('user_id')}"
            uname = html.escape(raw_uname)
            uid = u.get("user_id", "")
            d_count = u.get("daily_count", 0) if u.get("daily_date") == today else 0
            base_lim = u.get("base_daily_limit", 3)
            b_cred = u.get("bonus_credits", 0)
            seen = html.escape(str(u.get("last_seen", "")))
            lines.append(f"{idx}. {uname} (ID: {uid})\n   Лимит: {d_count}/{base_lim} | Бонус: {b_cred} | Был: {seen}")
            
            btn_title = f"⚙ {raw_uname} (Лимит: {base_lim}, +{b_cred})"
            kb.append([{"text": btn_title, "callback_data": f"admin_user_{uid}"}])

    nav_row = []
    if page > 0:
        nav_row.append({"text": "◀️ Назад", "callback_data": f"admin_users_page_{page - 1}"})
    nav_row.append({"text": "🔄 Обновить", "callback_data": f"admin_users_page_{page}"})
    if page < total_pages - 1:
        nav_row.append({"text": "Вперед ▶️", "callback_data": f"admin_users_page_{page + 1}"})
    if nav_row:
        kb.append(nav_row)

    kb.append([{"text": "🔍 Найти по @username / ID", "callback_data": "admin_search_user"}])
    kb.append([{"text": "🔄 Сбросить суточные лимиты ВСЕМ", "callback_data": "admin_confirm_reset_all_view"}])
    kb.append([{"text": "◀️ Назад в админку", "callback_data": "admin_main"}])

    return "\n".join(lines), {"inline_keyboard": kb}

def render_admin_user_card(uid):
    db = load_db()
    user = db.get("users", {}).get(str(uid))
    if not user:
        return "Пользователь не найден.", {"inline_keyboard": [[{"text": "◀️ Назад к списку", "callback_data": "admin_users_page_0"}]]}

    today = datetime.now().strftime("%Y-%m-%d")
    d_count = user.get("daily_count", 0) if user.get("daily_date") == today else 0
    base_lim = user.get("base_daily_limit", 3)
    free_left = max(0, base_lim - d_count)
    b_cred = user.get("bonus_credits", 0)
    raw_uname = f"@{user.get('username')}" if user.get("username") else "без юзернейма"
    uname = html.escape(raw_uname)
    fname = html.escape(str(user.get("first_name", "Не указано")))
    tot = user.get("total_count", 0)
    stars = user.get("total_stars", 0)
    seen = html.escape(str(user.get("last_seen", "")))

    text = (
        f"👤 <b>КАРТОЧКА ПОЛЬЗОВАТЕЛЯ</b>\n\n"
        f"Юзернейм: {uname}\n"
        f"Имя: {fname}\n"
        f"Telegram ID: {uid}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Базовый дневной лимит: {base_lim} в день\n"
        f"⚡ Расход сегодня: {d_count} из {base_lim} (осталось: {free_left})\n"
        f"🎁 Доступно бонусных генераций: {b_cred}\n"
        f"📈 Всего создано артов: {tot}\n"
        f"🌟 Куплено через Stars: {stars}\n"
        f"🕒 Последняя активность: {seen}\n\n"
        "Выберите действие:"
    )

    kb = [
        [{"text": "✏️ Изменить базовый лимит", "callback_data": f"admin_edit_base_{uid}"}],
        [{"text": "🎁 Выдать генерации (бонус)", "callback_data": f"admin_grant_{uid}"}],
        [{"text": "🔄 Сбросить дневной расход в 0", "callback_data": f"admin_reset_daily_{uid}"}],
        [{"text": "◀️ К списку пользователей", "callback_data": "admin_users_page_0"},
         {"text": "🏠 Меню админки", "callback_data": "admin_main"}]
    ]
    return text, {"inline_keyboard": kb}

def render_admin_edit_base_menu(uid):
    db = load_db()
    user = db.get("users", {}).get(str(uid), {})
    raw_uname = f"@{user.get('username')}" if user.get("username") else f"ID {uid}"
    uname = html.escape(raw_uname)
    cur_base = user.get("base_daily_limit", 3)
    text = (
        f"✏️ <b>ИЗМЕНЕНИЕ БАЗОВОГО ЛИМИТА</b>\n\n"
        f"Пользователь: {uname} (ID: {uid})\n"
        f"Текущий базовый лимит: {cur_base} в день.\n\n"
        "Выберите новый лимит или введите число вручную:"
    )
    kb = [
        [{"text": "1 / день", "callback_data": f"admin_set_base_{uid}_1"},
         {"text": "3 (Станд.)", "callback_data": f"admin_set_base_{uid}_3"},
         {"text": "5 / день", "callback_data": f"admin_set_base_{uid}_5"}],
        [{"text": "10 / день", "callback_data": f"admin_set_base_{uid}_10"},
         {"text": "20 / день", "callback_data": f"admin_set_base_{uid}_20"},
         {"text": "50 / день", "callback_data": f"admin_set_base_{uid}_50"}],
        [{"text": "100 / день", "callback_data": f"admin_set_base_{uid}_100"},
         {"text": "9999 (Безлимит)", "callback_data": f"admin_set_base_{uid}_9999"}],
        [{"text": "⌨️ Ввести точное число", "callback_data": f"admin_custom_base_{uid}"}],
        [{"text": "◀️ Назад в карточку", "callback_data": f"admin_user_{uid}"}]
    ]
    return text, {"inline_keyboard": kb}

def render_admin_grant_menu(uid):
    db = load_db()
    user = db.get("users", {}).get(str(uid), {})
    raw_uname = f"@{user.get('username')}" if user.get("username") else f"ID {uid}"
    uname = html.escape(raw_uname)
    cur_bonus = user.get("bonus_credits", 0)
    text = (
        f"🎁 <b>ВЫДАЧА ДОПОЛНИТЕЛЬНЫХ ГЕНЕРАЦИЙ</b>\n\n"
        f"Пользователь: {uname} (ID: {uid})\n"
        f"Текущий бонусный баланс: {cur_bonus} генераций.\n\n"
        "Выберите, сколько генераций добавить пользователю:"
    )
    kb = [
        [{"text": "+1 арт", "callback_data": f"admin_add_grant_{uid}_1"},
         {"text": "+3 арта", "callback_data": f"admin_add_grant_{uid}_3"},
         {"text": "+5 артов", "callback_data": f"admin_add_grant_{uid}_5"}],
        [{"text": "+10 артов", "callback_data": f"admin_add_grant_{uid}_10"},
         {"text": "+20 артов", "callback_data": f"admin_add_grant_{uid}_20"},
         {"text": "+50 артов", "callback_data": f"admin_add_grant_{uid}_50"}],
        [{"text": "🚫 Сбросить бонус в 0", "callback_data": f"admin_add_grant_{uid}_reset"}],
        [{"text": "⌨️ Ввести любое число", "callback_data": f"admin_custom_grant_{uid}"}],
        [{"text": "◀️ Назад в карточку", "callback_data": f"admin_user_{uid}"}]
    ]
    return text, {"inline_keyboard": kb}

def render_admin_history(page=0):
    db = load_db()
    history = db.get("history", [])
    per_page = 5
    total_pages = max(1, (len(history) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    page_items = history[start_idx : start_idx + per_page]

    lines = [f"🖼 <b>ИСТОРИЯ ГЕНЕРАЦИЙ (Стр. {page + 1}/{total_pages})</b>\nНажмите на кнопку '🖼 Арт', чтобы просмотреть изображение прямо в чате:\n"]
    kb = []
    art_row = []

    if not history:
        lines.append("Генераций еще не было.")
    else:
        for idx, h in enumerate(page_items, start_idx + 1):
            raw_uname = f"@{h.get('username')}" if h.get("username") and h.get("username") != "без юзернейма" else f"ID {h.get('user_id')}"
            uname = html.escape(raw_uname)
            t = h.get("time", "")
            mode = "Uncensored" if h.get("mode") == "nsfw" else "SFW"
            res = h.get("res", "")
            el = h.get("elapsed", 0)
            has_img = bool(h.get("image_path") and os.path.exists(h.get("image_path", "")))
            
            art_label = f"#{idx}"
            if h.get("is_custom"):
                p = html.escape(str(h.get("prompt", "")[:90]))
                lines.append(f"{art_label}. [{t}] {uname}\n   Кастомный: '{p}'\n   Параметры: {mode}, {res}, {el} сек.")
            else:
                c = html.escape(str(h.get("char", "")))
                po = html.escape(str(h.get("pose", "")))
                en = html.escape(str(h.get("env", "")))
                lines.append(f"{art_label}. [{t}] {uname}\n   {c} | {po} | {en}\n   Параметры: {mode}, {res}, {el} сек.")

            h_id = h.get("id", str(idx))
            btn_txt = f"🖼 Арт #{idx}" if has_img else f"ℹ️ Инфо #{idx}"
            art_row.append({"text": btn_txt, "callback_data": f"admin_view_art_{h_id}"})
            if len(art_row) == 3:
                kb.append(art_row)
                art_row = []

    if art_row:
        kb.append(art_row)

    nav_row = []
    if page > 0:
        nav_row.append({"text": "◀️ Назад", "callback_data": f"admin_hist_page_{page - 1}"})
    nav_row.append({"text": "🔄 Обновить", "callback_data": f"admin_hist_page_{page}"})
    if page < total_pages - 1:
        nav_row.append({"text": "Вперед ▶️", "callback_data": f"admin_hist_page_{page + 1}"})
    if nav_row:
        kb.append(nav_row)

    kb.append([{"text": "◀️ Назад в админку", "callback_data": "admin_main"}])
    return "\n\n".join(lines), {"inline_keyboard": kb}

def render_admin_messages():
    db = load_db()
    messages = db.get("messages", [])
    lines = ["💬 <b>ПОСЛЕДНИЕ СООБЩЕНИЯ В ЧАТАХ (Последние 15)</b>\n"]

    if not messages:
        lines.append("Сообщений еще нет.")
    else:
        for idx, m in enumerate(messages[:15], 1):
            raw_uname = f"@{m.get('username')}" if m.get("username") and m.get("username") != "без юзернейма" else f"ID {m.get('user_id')}"
            uname = html.escape(raw_uname)
            t = m.get("time", "")
            txt = html.escape(str(m.get("text", "")[:120]))
            lines.append(f"{idx}. [{t}] {uname}:\n   '{txt}'")

    text = "\n\n".join(lines)
    markup = {
        "inline_keyboard": [
            [{"text": "🔄 Обновить", "callback_data": "admin_messages"}],
            [{"text": "◀️ Назад в админку", "callback_data": "admin_main"}]
        ]
    }
    return text, markup

def make_confirm_generation_menu(session, user_id=None, username=""):
    char_name = html.escape(str(session.get("char_name", "Не выбран")))
    pose_name = html.escape(str(session.get("pose_name", "Стандартная")))
    env_name = html.escape(str(session.get("env_name", "Без окружения")))
    width = session.get("width", 832)
    height = session.get("height", 1216)
    mode_text = "👗 В одежде (SFW)" if session.get("mode") == "sfw" else "🔥 Без одежды (NSFW)"
    
    cur_model_id = session.get("model", DEFAULT_MODEL)
    model_name = AVAILABLE_MODELS.get(cur_model_id, {}).get("name", "NoobAI XL")
    steps = int(session.get("steps", 20))
    if not is_admin(user_id, username):
        steps = max(15, min(25, steps))

    admin_flag, free_left, bonus_left, total_left = get_user_limits_status(user_id, username)
    if admin_flag:
        lim_str = "Безлимитный доступ (Администратор)"
    else:
        db = load_db()
        base_lim = db.get("users", {}).get(str(user_id), {}).get("base_daily_limit", 3) if user_id else 3
        if bonus_left > 0:
            lim_str = f"{free_left} из {base_lim} (+{bonus_left} бонусных)"
        else:
            lim_str = f"{free_left} из {base_lim}"

    text = (
        "❓ <b>ПОДТВЕРЖДЕНИЕ ГЕНЕРАЦИИ</b>\n\n"
        "Вы хотите запустить создание арта со следующими настройками?\n\n"
        f"👤 <b>Персонаж:</b> {char_name}\n"
        f"💃 <b>Поза:</b> {pose_name}\n"
        f"🏞 <b>Окружение:</b> {env_name}\n"
        f"⚙️ <b>Параметры:</b> {model_name} | {width}x{height} | {steps} samples | {mode_text}\n"
        f"📊 <b>Ваш лимит:</b> {lim_str}\n\n"
        "<i>С вашего баланса будет использована 1 генерация.</i>"
    )
    kb = [
        [{"text": "🚀 Да, сгенерировать!", "callback_data": "confirm_exec_generate"}],
        [{"text": "◀️ Отмена / Назад в меню", "callback_data": "menu_main"}]
    ]
    return text, {"inline_keyboard": kb}

def make_confirm_custom_menu(text_prompt, session, user_id=None, username=""):
    width = session.get("width", 832)
    height = session.get("height", 1216)
    mode_text = "👗 В одежде (SFW)" if session.get("mode") == "sfw" else "🔥 Без одежды (NSFW)"
    
    cur_model_id = session.get("model", DEFAULT_MODEL)
    model_name = AVAILABLE_MODELS.get(cur_model_id, {}).get("name", "NoobAI XL")
    steps = int(session.get("steps", 20))
    if not is_admin(user_id, username):
        steps = max(15, min(25, steps))

    admin_flag, free_left, bonus_left, total_left = get_user_limits_status(user_id, username)
    if admin_flag:
        lim_str = "Безлимитный доступ (Администратор)"
    else:
        db = load_db()
        base_lim = db.get("users", {}).get(str(user_id), {}).get("base_daily_limit", 3) if user_id else 3
        if bonus_left > 0:
            lim_str = f"{free_left} из {base_lim} (+{bonus_left} бонусных)"
        else:
            lim_str = f"{free_left} из {base_lim}"

    short_prompt = text_prompt[:150] + "..." if len(text_prompt) > 150 else text_prompt

    text = (
        "❓ <b>ПОДТВЕРЖДЕНИЕ ГЕНЕРАЦИИ</b>\n\n"
        "Вы хотите запустить генерацию по этому тексту?\n\n"
        f"📝 <b>Текст запроса:</b>\n<code>{html.escape(short_prompt)}</code>\n\n"
        f"⚙️ <b>Параметры:</b> {model_name} | {width}x{height} | {steps} samples | {mode_text}\n"
        f"📊 <b>Ваш лимит:</b> {lim_str}\n\n"
        "<i>С вашего баланса будет использована 1 генерация. Выберите действие:</i>"
    )
    kb = [
        [{"text": "✨ Сгенерировать с подробным ИИ-промтом", "callback_data": "confirm_exec_custom_ai"}],
        [{"text": "🚀 Сгенерировать текст как есть", "callback_data": "confirm_exec_custom"}],
        [{"text": "🔍 Улучшить и посмотреть теги", "callback_data": "custom_enhance_ai"}],
        [{"text": "👤 Установить как персонажа в меню", "callback_data": "custom_search_char"}],
        [{"text": "◀️ Отмена / Назад", "callback_data": "menu_main"}]
    ]
    return text, {"inline_keyboard": kb}

