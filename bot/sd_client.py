import os
import re
import gc
import time
import json
import base64
import urllib.request
from bot.config import (
    API_URL, CLOTHING_RE, active_lock, active_generations,
    generation_queue, gpu_lock, AVAILABLE_MODELS, DEFAULT_MODEL, DEFAULT_CFG_SCALE
)

def trim_system_memory():
    """
    Освобождает неиспользуемую память (Working Set) процесса бота
    и фонового процесса SD Forge / WebUI, предотвращая утечки до 15+ ГБ RAM.
    """
    gc.collect()
    try:
        import ctypes
        # Очищаем память текущего процесса бота
        ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
        # Ищем и очищаем Working Set всех процессов Python (SD Forge launch.py, torch и т.д.)
        import psutil
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmd = " ".join(p.info.get('cmdline') or []).lower()
                if "launch.py" in cmd or "stable-diffusion" in cmd or "forge" in cmd or "webui" in cmd:
                    h = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, p.pid)
                    if h:
                        ctypes.windll.psapi.EmptyWorkingSet(h)
                        ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                pass
    except Exception:
        pass

def filter_clothing_tags(prompt_str):
    tags = [t.strip() for t in prompt_str.split(',') if t.strip()]
    cleaned = []
    for t in tags:
        norm = t.strip().lower().replace('_', ' ')
        if not CLOTHING_RE.search(norm):
            cleaned.append(t)
    return ', '.join(cleaned)

def is_generation_busy():
    with active_lock:
        a_len = len(active_generations)
    return a_len > 0 or not generation_queue.empty() or gpu_lock.locked()

def generate_image(prompt, is_nsfw=True, width=832, height=1216, is_custom=False, steps=20, with_partner=False, model=DEFAULT_MODEL, char_gender="female", cfg_scale=DEFAULT_CFG_SCALE):
    width = min(max(512, width), 1500)
    height = min(max(512, height), 1500)
    width = (width // 8) * 8
    height = (height // 8) * 8

    p_low = prompt.lower()
    tags = {t.strip().lower() for t in prompt.split(",")}

    # В кастомном запросе пол из меню персонажа не должен переопределять текст.
    if is_custom:
        if "1boy" in tags and "1girl" not in tags:
            is_male = True
        elif "1girl" in tags and "1boy" not in tags:
            is_male = False
        else:
            is_male = None
    else:
        is_male = char_gender == "male"

    # Партнёра добавляем только когда пользователь явно включил эту настройку.
    has_partner = bool(with_partner and is_male is False and not is_custom)

    if has_partner:
        prompt = re.sub(r"(?i)(?:^|,)\s*solo\s*(?=,|$)", "", prompt)
        prompt = re.sub(r",\s*,+", ",", prompt).strip(" ,")
        if "1girl" not in tags:
            prompt = "1girl, " + prompt
        if "1boy" not in tags:
            prompt = "1boy, " + prompt
        neg_gender = "extra_person, 2boys, 3girls"
    elif is_male is True:
        if not is_custom and "1boy" not in tags:
            prompt = "1boy, solo, " + prompt
        neg_gender = "1girl, 2girls, extra_person" if not is_custom else ""
    elif is_male is False:
        if not is_custom and "1girl" not in tags:
            prompt = "1girl, solo, " + prompt
        neg_gender = "1boy, 2boys, extra_person" if not is_custom else ""
    else:
        # Для кастомного запроса с неизвестным составом сцены ничего не угадываем.
        neg_gender = ""

    # Дальше проверяем уже исправленный prompt.
    p_low = prompt.lower()

    # Проверка на наличие специфического цвета кожи/шерсти в запросе
    has_custom_skin = any(k in p_low for k in [
        "dark skin", "dark-skinned", "tan skin", "tanned", "brown skin", "black skin", "gyaru",
        "yellow fur", "yellow skin", "orange skin", "orange fur", "golden fur", "green skin",
        "blue skin", "purple skin", "gray skin", "grey fur", "white fur", "black fur", "wolf girl", "anthro", "furry"
    ])

    # Извлечение параметров стиля и LoRA для конкретной выбранной модели
    model_info = AVAILABLE_MODELS.get(model, AVAILABLE_MODELS.get(DEFAULT_MODEL, {}))
    checkpoint_name = model_info.get("checkpoint", "NoobAI-XL-Vpred-v1.0.safetensors")
    lora_name = model_info.get("lora_name", "gummyflux_v2")
    lora_weight = model_info.get("lora_weight", 0.8)
    style_prefix = model_info.get("style_prefix", "cstyle, glossy skin, sticker outline")
    lora_tag = f"<lora:{lora_name}:{lora_weight}>"

    # Строгий негативный фильтр против 3D, фотореализма, монохрома и противоестественного пожелтения кожи
    color_anti_yellow = "" if has_custom_skin else ", (yellow skin, orange skin, colored skin, unnatural skin tone:1.35)"
    base_negative = f"(3d, realistic, photo, cgi, render, blender, doll, figure:1.45), (monochrome, greyscale, sketch:1.3){color_anti_yellow}"

    if is_custom:
        full_prompt = (
            f"masterpiece, best quality, newest, "
            f"{style_prefix}, {lora_tag}, {prompt}"
        )
        neg_prompt = (
            f"{base_negative}, (text, words, signature, watermark, username, caption, font, letter:1.3), "
            f"worst quality, low quality, bad anatomy, bad hands, blurry, mutated, extra limbs, extra fingers, {neg_gender}".strip(", ")
        )
    elif is_nsfw:
        cleaned_prompt = filter_clothing_tags(prompt)
        body_tags = "nsfw, nude"
        full_prompt = (
            f"masterpiece, best quality, newest, {style_prefix}, {lora_tag}, "
            f"{cleaned_prompt}, {body_tags}"
        )
        neg_prompt = (
            f"{base_negative}, (clothes, clothing, outfit, costume, fabric, dress, skirt, shirt, pants, shorts, bra, "
            "panties, underwear, swimwear, swimsuit, apron, gloves, socks, covering, censor, censored, "
            "mosaic censoring, bar censor:1.4), (text, words, signature, watermark, username, caption, font, letter:1.3), "
            f"worst quality, low quality, bad anatomy, bad hands, blurry, mutated, extra limbs, extra fingers, {neg_gender}".strip(", ")
        )
    else:
        body_tags = "sfw"
        full_prompt = (
            f"masterpiece, best quality, newest, {style_prefix}, {lora_tag}, "
            f"{prompt}, {body_tags}"
        )
        neg_prompt = (
            f"{base_negative}, (nsfw, nude, naked:1.3), "
            "(text, words, signature, watermark, username, caption, font, letter:1.3), "
            f"worst quality, low quality, bad anatomy, bad hands, blurry, mutated, extra limbs, extra fingers, {neg_gender}".strip(", ")
        )

    try:
        cfg_val = round(min(max(1.0, float(cfg_scale)), 15.0), 1)
    except Exception:
        cfg_val = DEFAULT_CFG_SCALE

    # Шаги семплирования (Samples) и параметры генерации
    payload = {
        "prompt": full_prompt,
        "negative_prompt": neg_prompt,
        "steps": max(5, min(int(steps), 60)),
        "cfg_scale": cfg_val,
        "width": width,
        "height": height,
        "sampler_name": "Euler a",
        "override_settings": {
            "sd_model_checkpoint": checkpoint_name,
            "fp8_storage": "Enable for SDXL"
        }
    }

    start = time.time()
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(API_URL, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            elapsed = round(time.time() - start, 1)
            if res.get("images"):
                return base64.b64decode(res["images"][0]), elapsed
    except Exception as e:
        print(f"Gen error: {e}", flush=True)
    finally:
        # Автоматическая очистка Working Set памяти SD Forge и Python после каждого рендера
        trim_system_memory()
    return None, 0
