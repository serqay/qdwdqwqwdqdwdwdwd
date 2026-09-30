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
    Освобождает неиспользуемую память (Working Set) процесса бота.
    """
    gc.collect()

def filter_clothing_tags(prompt_str):
    tags = [t.strip() for t in prompt_str.split(',') if t.strip()]
    cleaned = []
    for t in tags:
        norm = t.strip().lower().replace('_', ' ')
        if not CLOTHING_RE.search(norm):
            cleaned.append(t)
    return ', '.join(cleaned)

def is_backend_online(timeout=1.5):
    """
    Быстрая проверка доступности сервера генерации (SD Forge).
    Работает как при локальном запуске, так и через SSH reverse-tunnel на VPS.
    """
    try:
        req = urllib.request.Request("http://127.0.0.1:7860/sdapi/v1/progress?skip_current_image=true")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False

def is_generation_busy():
    with active_lock:
        a_len = len(active_generations)
    return a_len > 0 or not generation_queue.empty() or gpu_lock.locked()

def load_prompt_settings():
    """
    Загружает актуальные настройки промптов и параметров генерации из prompt_settings.json.
    Ищет файл локально или в рабочей директории VPS.
    """
    candidate_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompt_settings.json"),
        os.path.join(os.getcwd(), "prompt_settings.json"),
        "/root/ai_bot/prompt_settings.json"
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

def generate_image(prompt, is_nsfw=True, width=832, height=1216, is_custom=False, steps=28, with_partner=False, model=DEFAULT_MODEL, char_gender="female", cfg_scale=DEFAULT_CFG_SCALE):
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
    dyn = load_prompt_settings()
    model_info = AVAILABLE_MODELS.get(model, AVAILABLE_MODELS.get(DEFAULT_MODEL, {}))

    if model == "noobai":
        checkpoint_name = dyn.get("checkpoint") or model_info.get("checkpoint", "NoobAI-XL-Vpred-v1.0.safetensors")
        lora_name = dyn.get("lora_name", model_info.get("lora_name", "gummyflux"))
        raw_w = dyn.get("lora_weight", model_info.get("lora_weight", 0.95))
        style_prefix = dyn.get("style_prefix", model_info.get("style_prefix", "gummyflux, cstyle"))
        quality_suffix = dyn.get("quality_suffix", "masterpiece, best quality, rich color, detailed shading, vibrant colors")
        base_negative = dyn.get("base_negative", "(monochrome, greyscale, sketch, lineart, uncolored, coloring book:1.4), low quality, worst quality, blurry, deformed, bad anatomy, bad hands, missing fingers, extra fingers, 3d, realistic, photo, ugly, disfigured, text, watermark")
        clothing_negative = dyn.get("clothing_negative", "(clothes, clothing, outfit, costume, fabric, dress, skirt, shirt, pants, shorts, bra, panties, underwear, swimwear, swimsuit, apron, gloves, socks, covering, censor, censored, mosaic censoring, bar censor:1.4)")
        sfw_negative = dyn.get("sfw_negative", "(nsfw, nude, naked:1.3)")
        sampler_name = dyn.get("sampler_name", "Euler")
        clip_skip = int(dyn.get("clip_skip", 1))
    else:
        checkpoint_name = model_info.get("checkpoint", "Illustrious-XL-v0.1.safetensors")
        lora_name = model_info.get("lora_name", "artist_style_lora")
        raw_w = model_info.get("lora_weight", 0.85)
        style_prefix = model_info.get("style_prefix", "cstyle, glossy skin, sticker outline")
        quality_suffix = "masterpiece, best quality, rich color, detailed shading, vibrant colors"
        base_negative = "(monochrome, greyscale, sketch, lineart, uncolored, coloring book:1.4), low quality, worst quality, blurry, deformed, bad anatomy, bad hands, missing fingers, extra fingers, 3d, realistic, photo, ugly, disfigured, text, watermark"
        clothing_negative = "(clothes, clothing, outfit, costume, fabric, dress, skirt, shirt, pants, shorts, bra, panties, underwear, swimwear, swimsuit, apron, gloves, socks, covering, censor, censored, mosaic censoring, bar censor:1.4)"
        sfw_negative = "(nsfw, nude, naked:1.3)"
        sampler_name = dyn.get("sampler_name", "Euler")
        clip_skip = int(dyn.get("clip_skip", 1))

    try:
        lora_w_str = str(round(float(raw_w), 2))
    except Exception:
        lora_w_str = "0.95"
    lora_tag = f"<lora:{lora_name}:{lora_w_str}>" if lora_name else ""

    if is_custom:
        prefix_parts = []
        if lora_tag and "<lora:" not in p_low:
            prefix_parts.append(lora_tag)
        if style_prefix:
            for s_part in [s.strip() for s in style_prefix.split(",") if s.strip()]:
                if s_part.lower() not in p_low:
                    prefix_parts.append(s_part)

        custom_prefix = ", ".join(prefix_parts)
        
        if is_nsfw:
            body_tags = (
                "nsfw, completely nude, no clothes, bare body, nipples, bare breasts, "
                "pussy, navel, bare legs, uncensored, voluptuous, curvy figure, wide hips, thick thighs, "
                "hourglass figure, full body"
            )
            prompt = filter_clothing_tags(prompt)
            neg_prompt = f"{clothing_negative}, {base_negative}, {neg_gender}".strip(", ")
        else:
            body_tags = (
                "sfw, fully clothed, wearing stylish outfit, detailed clothing, "
                "voluptuous, curvy figure, wide hips, thick thighs, hourglass figure, full body"
            )
            neg_prompt = f"{sfw_negative}, {base_negative}, {neg_gender}".strip(", ")

        full_prompt = f"{custom_prefix}, {prompt}, {body_tags}, {quality_suffix}".strip(", ")
    elif is_nsfw:
        cleaned_prompt = filter_clothing_tags(prompt)
        body_tags = (
            "nsfw, completely nude, no clothes, bare body, nipples, bare breasts, "
            "pussy, navel, bare legs, uncensored, voluptuous, curvy figure, wide hips, thick thighs, "
            "hourglass figure, full body"
        )
        full_prompt = f"{lora_tag} {style_prefix}, {cleaned_prompt}, {body_tags}, {quality_suffix}".strip(", ")
        neg_prompt = f"{clothing_negative}, {base_negative}, {neg_gender}".strip(", ")
    else:
        body_tags = (
            "sfw, fully clothed, wearing stylish outfit, detailed clothing, "
            "voluptuous, curvy figure, wide hips, thick thighs, hourglass figure, full body"
        )
        full_prompt = f"{lora_tag} {style_prefix}, {prompt}, {body_tags}, {quality_suffix}".strip(", ")
        neg_prompt = f"{sfw_negative}, {base_negative}, {neg_gender}".strip(", ")

    try:
        cfg_val = round(min(max(1.0, float(cfg_scale)), 15.0), 1)
    except Exception:
        cfg_val = DEFAULT_CFG_SCALE

    # DynamicThresholding (CFG-Fix) — mimic_scale из настроек, по умолчанию 7.0
    dt_enabled = bool(dyn.get("dt_enabled", True))
    try:
        dt_mimic = round(float(dyn.get("dt_mimic_scale", 7.0)), 1)
    except Exception:
        dt_mimic = 7.0

    # Шаги семплирования (Samples) и параметры генерации
    payload = {
        "prompt": full_prompt,
        "negative_prompt": neg_prompt,
        "steps": max(5, min(int(steps), 60)),
        "cfg_scale": cfg_val,
        "width": width,
        "height": height,
        "sampler_name": sampler_name,
        "override_settings": {
            "sd_model_checkpoint": checkpoint_name,
            "CLIP_stop_at_last_layers": clip_skip,
            "fp8_storage": "Enable for SDXL"
        },
        "alwayson_scripts": {
            "DynamicThresholding (CFG-Fix) Integrated": {
                "args": [
                    dt_enabled,   # enabled
                    dt_mimic,     # mimic_scale
                    1.0,          # threshold_percentile
                    "Constant",   # mimic_mode
                    0.0,          # mimic_scale_min
                    "Constant",   # cfg_mode
                    0.0,          # cfg_scale_min
                    1.0,          # sched_val
                    "enable",     # separate_feature_channels
                    "MEAN",       # scaling_startpoint
                    "AD",         # variability_measure
                    1.0           # interpolate_phi
                ]
            }
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
