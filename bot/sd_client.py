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
    wants_futanari = any(k in p_low for k in ["futanari", "dickgirl", "shemale"])
    wants_toy = any(k in p_low for k in ["dildo", "sex toy", "strapon", "strap-on", "vibrator", "anal bead"])

    has_female_tag = any(k in p_low for k in ["1girl", "2girls", "female", "woman", "girl"])
    has_male_tag = any(k in p_low for k in ["1boy", "2boys", "1man", "male", "homdan", "cloud strife", "zoro", "dante", "gojo"])

    if char_gender == "male":
        is_male = True
    elif char_gender == "female":
        is_male = False
    else:
        is_male = has_male_tag and not has_female_tag

    # Explicit couple / partner tags (only explicit interactions, never generic solo poses)
    explicit_couple_tags = [
        "1girl and 1boy", "hetero sex", "heterosexual sex", "couple sex", "intercourse",
        "fellatio", "blowjob", "paizuri", "titfuck", "creampie", "cum inside", "cum on breasts",
        "double penetration", "group sex", "gangbang", "threesome",
        "секс", "минет", "отсос", "куни"
    ]
    has_partner = (with_partner and not is_male) or any(k in p_low for k in explicit_couple_tags)

    if has_partner:
        # Strip 'solo' tag so diffusion model renders exactly 2 people instead of fusing them into 1 mutant/futanari
        prompt = re.sub(r'\b(solo)\b,?\s*', '', prompt, flags=re.IGNORECASE)
        if "1boy" not in prompt.lower():
            if re.search(r'\b1girl\b', prompt, flags=re.IGNORECASE):
                prompt = re.sub(r'\b1girl\b', '1girl, 1boy, couple, hetero', prompt, count=1, flags=re.IGNORECASE)
            else:
                prompt = f"1girl, 1boy, couple, hetero, {prompt}"
        male_partner_tags = (
            "1boy, male, muscular male, faceless male, "
            "penis, large penis, erection, hard cock, veiny penis, testicles, balls, "
            "uncensored, hetero, heterosexual sex, sex, penetration, 1girl and 1boy, intimacy"
        )
        neg_extra_parts = []
        if not wants_futanari:
            neg_extra_parts.append("(futanari, dickgirl:1.4)")
        if not wants_toy:
            neg_extra_parts.append("(dildo, sex toy, strap-on, vibrator:1.4)")
        neg_extra_parts.append("(extra limbs, extra hands, extra legs, deformed penis, 2penises:1.3)")
        neg_extra_parts.append("(3girls, 2boys, group, extra person, multiple persons:1.2)")
        neg_gender = ", ".join(neg_extra_parts)
    elif is_male:
        if "1boy" not in prompt.lower() and "solo" not in prompt.lower():
            prompt = f"1boy, solo, {prompt}"
        neg_gender = (
            "(female, woman, breasts, cleavage, pussy, 1girl, 2girls, futanari, dickgirl:1.4), "
            "(extra person, multiple persons, 2boys:1.3)"
        )
    else:
        if "1girl" not in prompt.lower() and "solo" not in prompt.lower():
            prompt = f"1girl, solo, {prompt}"
        neg_female_parts = []
        if not wants_futanari:
            neg_female_parts.append("(futanari, dickgirl, penis, testicles, balls:1.4)")
        if not wants_toy:
            neg_female_parts.append("(dildo, sex toy, strap-on, vibrator:1.4)")
        neg_female_parts.append("(1boy, 2boys, male:1.4)")
        neg_female_parts.append("(extra person, multiple persons, 2girls:1.3)")
        neg_gender = ", ".join(neg_female_parts)

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
        if has_partner and is_nsfw:
            full_prompt = f"masterpiece, best quality, newest, {style_prefix}, {lora_tag}, {prompt}, {male_partner_tags}"
        else:
            full_prompt = f"masterpiece, best quality, newest, {style_prefix}, {lora_tag}, {prompt}"
        neg_prompt = (
            f"{base_negative}, (text, words, signature, watermark, username, caption, font, letter:1.3), "
            f"worst quality, low quality, bad anatomy, bad hands, blurry, mutated, extra limbs, extra fingers, {neg_gender}".strip(", ")
        )
    elif is_nsfw:
        cleaned_prompt = filter_clothing_tags(prompt)
        skin_tag = "" if has_custom_skin else "fair skin, "
        if is_male:
            male_skin = "" if has_custom_skin else "fair skin, "
            body_tags = f"nsfw, completely nude, no clothes, bare body, {male_skin}nipples, penis, balls, athletic, toned, bare legs, uncensored"
        else:
            female_body_tags = (
                f"nsfw, completely nude, no clothes, bare body, {skin_tag}nipples, bare breasts, "
                "pussy, navel, bare legs, uncensored, voluptuous, curvy figure, wide hips, thick thighs, hourglass figure"
            )
            if has_partner:
                body_tags = f"{female_body_tags}, {male_partner_tags}"
            else:
                body_tags = female_body_tags

        full_prompt = (
            f"masterpiece, best quality, newest, {style_prefix}, {lora_tag}, "
            f"{cleaned_prompt}, {body_tags}, full body"
        )
        neg_prompt = (
            f"{base_negative}, (clothes, clothing, outfit, costume, fabric, dress, skirt, shirt, pants, shorts, bra, "
            "panties, underwear, swimwear, swimsuit, apron, gloves, socks, covering, censor, censored, "
            "mosaic censoring, bar censor:1.4), (text, words, signature, watermark, username, caption, font, letter:1.3), "
            f"worst quality, low quality, bad anatomy, bad hands, blurry, mutated, extra limbs, extra fingers, {neg_gender}".strip(", ")
        )
    else:
        skin_tag = "" if has_custom_skin else "fair skin, "
        if is_male:
            male_skin = "" if has_custom_skin else "fair skin, "
            body_tags = f"sfw, fully clothed, {male_skin}wearing stylish outfit, detailed clothing, athletic, handsome"
        else:
            body_tags = (
                f"sfw, fully clothed, {skin_tag}wearing stylish outfit, detailed clothing, "
                "voluptuous, curvy figure, wide hips, thick thighs, hourglass figure"
            )
        full_prompt = (
            f"masterpiece, best quality, newest, {style_prefix}, {lora_tag}, "
            f"{prompt}, {body_tags}, full body"
        )
        neg_prompt = (
            f"{base_negative}, (nsfw, nude, naked, bare, exposed, cleavage, nipples, pussy, uncensored, navel, bare legs:1.4), "
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
