import re
import json
import base64
import urllib.request
from bot.config import (
    OMNIROUTE_URL, OMNIROUTE_KEY,
    OMNIROUTE_TEXT_MODEL, OMNIROUTE_VISION_MODEL
)

def _clean_tag_response(raw_text):
    if not raw_text:
        return ""
    text = raw_text.strip()
    
    # Удаляем markdown-блоки кода ```...```
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()
    
    # Удаляем префиксы вроде "Tags:", "Danbooru tags:", "Result:"
    text = re.sub(r"^(danbooru\s*tags|tags|result|output):\s*", "", text, flags=re.IGNORECASE)
    
    # Разделяем по запятым и переводам строк, чистим пробелы
    raw_tags = [t.strip().strip("'\"`") for t in text.replace("\n", ", ").split(",") if t.strip()]
    
    filtered = []
    seen = set()
    forbidden_prefixes = ("here are", "note:", "prompt:", "tags:", "danbooru:", "as requested", "here is", "this is")
    unwanted_tags = {
        "text", "english_text", "japanese_text", "chinese_text", "korean_text",
        "signature", "watermark", "username", "artist_name", "logo", "caption",
        "doodles", "speech_bubble", "comic", "sample", "translated", "bad_anatomy",
        "parody", "commentary", "copyright_name",
        "dynamic_lighting", "rim_lighting", "cinematic_lighting", "ray_tracing",
        "photorealistic", "realistic", "3d", "render", "cgi", "octane_render", "unreal_engine"
    }
    
    for t in raw_tags:
        t_clean = t.strip()
        if not t_clean:
            continue
        if any(t_clean.lower().startswith(p) for p in forbidden_prefixes):
            continue
        # Приводим к нижнему регистру
        t_clean = t_clean.lower()
        if t_clean in unwanted_tags:
            continue
        # Экранируем скобки для синтаксиса Stable Diffusion WebUI, если они еще не экранированы
        t_clean = re.sub(r"(?<!\\)\(", r"\(", t_clean)
        t_clean = re.sub(r"(?<!\\)\)", r"\)", t_clean)
        if t_clean not in seen:
            seen.add(t_clean)
            filtered.append(t_clean)
            
    return ", ".join(filtered)

def describe_character_by_name(char_name):
    """
    Запрашивает через ИИ точный и четкий набор визуальных Danbooru-тегов
    для персонажа по его имени.
    """
    norm_name = re.sub(r'[\s_]+', ' ', char_name.strip().lower())
    if "homdan" in norm_name:
        return "1boy, solo, homdan \\(minecraft\\), dark skin, dark-skinned male, bear_ears, animal_ears, brown_hair, short_hair, curly_hair, mouth_mask, print_mask, black_mask, blue_hoodie, open_hoodie, blue_jacket, white_shirt"

    prompt = (
        f"You are a master anime tagger, booru annotator, and prompt engineer for Stable Diffusion XL / NoobAI.\n"
        f"Given the character '{char_name}', produce an exhaustive, hyper-detailed, and ultra-accurate Danbooru tag sequence "
        f"that captures every single visual nuance of their design for high-end image generation.\n\n"
        f"Strictly adhere to the 15 Rules of Booru Prompt Composition:\n"
        f"Rule 1 (Subject Count & Gender): Begin strictly with '1girl, solo' (or '1boy, solo' if male; never mix gender tags on a solo subject).\n"
        f"Rule 2 (Canonical Identity): Exact character tag and series/franchise tag in booru syntax with underscores (e.g. '{char_name.lower().replace(' ', '_')}').\n"
        f"Rule 3 (Rating & Modesty): Accurately reflect the character's signature canonical clothing layers; do not insert conflicting nude/exposure tags into clothed designs.\n"
        f"Rule 4 (Head & Skin Complexion): Exact skin tone (fair_skin, pale_skin, tan, dark_skin), complexion, facial marks (mole, freckles, scar).\n"
        f"Rule 5 (Eyes & Gaze): Exact iris color, pupil shape (slit_pupils, ringed_eyes, etc.), detailed eyelashes, eye shadow, eyebrows, and gaze direction (looking_at_viewer).\n"
        f"Rule 6 (Facial Expression): Explicit mouth/lip state and emotion (smile, parted_lips, closed_mouth, confident, blush, seductive_smile).\n"
        f"Rule 7 (Hair Architecture & Physics): Exact primary/accent colors, length, specific cut (bangs, blunt_bangs, sidelocks, ahoge, ponytail, twintails, braids, messy_hair), hair movement (floating_hair), and hair accessories (ribbon, hairpin, hairband).\n"
        f"Rule 8 (Body Anatomy & Proportions): Breast size, detailed physique (curvy, hourglass_figure, wide_hips, thick_thighs, slender, athletic, toned), collarbone, navel, skin highlights.\n"
        f"Rule 9 (Species & Non-Human Traits): Animal ears, tail, horns, wings, fangs, elf_ears, halo, or species-specific markings where applicable.\n"
        f"Rule 10 (Layered Costume Hierarchy): Complete piece-by-piece breakdown from inner to outer layers (innerwear, top/blouse/shirt, coat/jacket, corset/vest, skirt/shorts/pants, belt, legwear/stockings, boots/shoes).\n"
        f"Rule 11 (Fabrics, Textures & Trims): Concrete material descriptors (leather, silk, denim, lace, velvet, gold_trim, metallic, sheer).\n"
        f"Rule 12 (Accessories & Props): Choker, necklace, earrings, bracelets, belts, gloves/fingerless_gloves, pouches, ribbons, weapons, signature held props.\n"
        f"Rule 13 (Framing & View Angle): Presentation framing (full_body or upper_body) with clean, unobstructed composition.\n"
        f"Rule 14 (Pose & Posture): Characteristic stance (standing, hand_on_hip, dynamic_stance, elegant_posture).\n"
        f"Rule 15 (Tag Hygiene & Format): Output ONLY authentic, lowercase, comma-separated Danbooru tags on a single line. Multi-word tags MUST use underscores. No conversational text, no markdown, no code blocks, no backticks."
    )
    
    models_to_try = [
        "antigravity/gemini-3.7-flash-high",
        OMNIROUTE_TEXT_MODEL
    ]
    
    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.25,
            "max_tokens": 1500
        }
        
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                OMNIROUTE_URL,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OMNIROUTE_KEY}"
                }
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                cleaned = _clean_tag_response(content)
                if cleaned:
                    low = cleaned.lower()
                    has_girl = "1girl" in low or "2girls" in low or "female" in low
                    has_boy = "1boy" in low or "2boys" in low or "1man" in low or " male" in low or "boy, " in low
                    if not has_girl and not has_boy:
                        cleaned = f"1girl, solo, {cleaned}"
                    elif has_boy and not has_girl and not cleaned.startswith("1boy"):
                        cleaned = f"1boy, solo, {cleaned}"
                    elif has_girl and not has_boy and not cleaned.startswith("1girl"):
                        cleaned = f"1girl, solo, {cleaned}"
                    return cleaned
        except Exception as e:
            print(f"AI describe_character error ({model}): {e}", flush=True)
            
    # Фолбек, если сервис временно недоступен
    clean_name = char_name.strip().lower().replace(" ", "_")
    norm = char_name.lower()
    prefix = "1boy, solo" if any(w in norm for w in ["boy", "man", "male", "guy", "homdan"]) else "1girl, solo"
    return f"{prefix}, {clean_name}"

def describe_character_by_photo(image_bytes):
    """
    Анализирует переданное изображение через мультимодальный ИИ
    с максимально исчерпывающей детализацией внешности, одежды,
    аксессуаров, прически, черт лица и позы в формате Danbooru-тегов.
    """
    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    
    prompt = (
        "You are an elite anime tagging specialist and booru dataset annotator for Stable Diffusion XL.\n"
        "Examine the provided image with extreme scrutiny and perform an exhaustive, ultra-detailed visual breakdown.\n"
        "Every single observable detail of the character MUST be captured into accurate Danbooru tags.\n\n"
        "Tagging guidelines (15 Rules of Booru Visual Extraction):\n"
        "Rule 1 (Subject Count & Gender): '1girl, solo' (or '1boy, solo' if male).\n"
        "Rule 2 (Canonical Identity): Canonical character tag and franchise/series in booru format (e.g., 'tifa_lockhart, final_fantasy_vii') if recognized.\n"
        "Rule 3 (Modesty & Attire State): Exact state of dress (fully_clothed, bare_shoulders, cleavage, or completely nude).\n"
        "Rule 4 (Skin & Complexion): Skin tone (pale_skin, tan, dark_skin), complexion, blushed_cheeks, freckles, mole, scar, body_markings.\n"
        "Rule 5 (Eyes & Gaze): EXACT eye color, pupil shape (slit_pupils, ringed_eyes, heart_pupils), eyelashes, eyeshadow, eyebrows, looking_at_viewer.\n"
        "Rule 6 (Facial Expression): Exact expression (smile, parted_lips, open_mouth, smirk, fang, seductive_smile, blush).\n"
        "Rule 7 (Hair Structure & Physics): Primary/secondary colors, highlights, length (short_hair, long_hair), styling (bangs, sidelocks, twintails, ponytail, messy_hair, braids), hair accessories (ribbon, hairpin, hairband).\n"
        "Rule 8 (Body & Physique): Bust size (small_breasts, medium_breasts, large_breasts), body shape (slender, curvy, hourglass_figure, wide_hips, thick_thighs, toned, athletic).\n"
        "Rule 9 (Species & Non-Human Features): Animal ears, wolf_ears, fox_ears, horns, halo, head_wings, fangs, elf_ears, tail.\n"
        "Rule 10 (Layered Costume): Complete layer-by-layer breakdown from top to bottom (headwear, collar/choker, top/jacket/blouse, skirt/pants, legwear/stockings, footwear/boots).\n"
        "Rule 11 (Fabrics & Textures): Exact materials and trims (leather, silk, lace, denim, gold_trim, sheer).\n"
        "Rule 12 (Accessories & Details): Piercings, earrings, rings, belts, pouches, ribbons, weapons if visible.\n"
        "Rule 13 (Framing & View Angle): Framing (full_body, upper_body, portrait, cowboy_shot) and camera angle.\n"
        "Rule 14 (Pose & Posture): Body position (standing, sitting, kneeling, leaning_forward, hand_on_hip, dynamic_pose).\n"
        "Rule 15 (Tag Hygiene & Format): Output ONLY authentic lowercase Danbooru booru tags separated by commas. Multi-word tags MUST use underscores. No buzzwords like 'masterpiece' or 'high quality'.\n\n"
        "- Format your output EXACTLY as:\n"
        "NAME: <character name and source, or a clear descriptive name>\n"
        "TAGS: <comma-separated list of all Danbooru tags>\n"
        "Do not output any markdown code blocks, backticks, or intro/outro explanations."
    )
    
    payload = {
        "model": OMNIROUTE_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_img}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.2,
        "max_tokens": 2000
    }
    
    try:
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            OMNIROUTE_URL,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OMNIROUTE_KEY}"
            }
        )
        with urllib.request.urlopen(req, timeout=50) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            
            char_name = "Персонаж по фото"
            tags_lines = []
            is_in_tags = False
            
            for line in content.split("\n"):
                line_s = line.strip()
                if not line_s:
                    continue
                if line_s.upper().startswith("NAME:"):
                    name_cand = line_s[5:].strip().strip("*`")
                    if name_cand and name_cand.lower() != "unknown":
                        char_name = name_cand
                    is_in_tags = False
                elif line_s.upper().startswith("TAGS:"):
                    is_in_tags = True
                    tags_content = line_s[5:].strip()
                    if tags_content:
                        tags_lines.append(tags_content)
                elif is_in_tags:
                    tags_lines.append(line_s)
            
            if tags_lines:
                tags_part = ", ".join(tags_lines)
            else:
                content_clean = re.sub(r"^NAME:.*$", "", content, flags=re.MULTILINE|re.IGNORECASE).strip()
                content_clean = re.sub(r"^TAGS:\s*", "", content_clean, flags=re.IGNORECASE).strip()
                tags_part = content_clean
                
            cleaned_tags = _clean_tag_response(tags_part)
            if cleaned_tags:
                low_p = cleaned_tags.lower()
                has_g = "1girl" in low_p or "female" in low_p
                has_b = "1boy" in low_p or "1man" in low_p or " male" in low_p
                if not has_g and not has_b:
                    cleaned_tags = f"1girl, solo, {cleaned_tags}"
                elif has_b and not has_g and not cleaned_tags.startswith("1boy"):
                    cleaned_tags = f"1boy, solo, {cleaned_tags}"
                elif has_g and not has_b and not cleaned_tags.startswith("1girl"):
                    cleaned_tags = f"1girl, solo, {cleaned_tags}"

            return char_name, cleaned_tags
    except Exception as e:
        print(f"AI describe_photo error: {e}", flush=True)
        return "Персонаж по фото", "1girl, solo, detailed anime girl"

def enhance_prompt_with_ai(user_prompt):
    """
    Превращает любую пользовательскую идею, короткий текст (на русском или английском)
    в исчерпывающий, профессиональный и ультра-детализированный набор Danbooru-тегов
    для Stable Diffusion XL / NoobAI.
    """
    if not user_prompt:
        return "1girl, solo, masterpiece, best quality"

    prompt = (
        "You are an elite master anime tagger, booru annotator, and prompt engineer for Stable Diffusion XL / NoobAI.\n"
        f"Transform the following user request into an exhaustive, hyper-detailed, and visually stunning sequence of Danbooru tags:\n"
        f"User Input: '{user_prompt}'\n\n"
        "Strictly adhere to the 15 Rules of Booru Prompt Engineering:\n"
        "Rule 1 (Subject Count & Gender): Begin strictly with '1girl, solo' (or '1boy, solo' if male; couple tags '1girl, 1boy, couple' only if explicitly requested).\n"
        "Rule 2 (Canonical Tagging): Identify and include exact booru character and franchise tags with underscores if any known franchise is referenced.\n"
        "Rule 3 (Concept Translation): Accurately translate any Russian or informal natural language concepts into canonical Danbooru tags.\n"
        "Rule 4 (Head & Skin Tone): Skin tone (pale_skin, fair_skin, tan), complexion, blushing, facial marks (mole, freckles, scar).\n"
        "Rule 5 (Eyes & Gaze): Exact iris color, pupil features, eyelashes, eyebrows, eye shadow, and looking_at_viewer.\n"
        "Rule 6 (Facial Expression): Concrete expression and mouth state (smile, parted_lips, open_mouth, smirk, blush, confident).\n"
        "Rule 7 (Hair Details & Physics): Primary/accent colors, length, styling (bangs, sidelocks, twintails, ponytail, messy_hair), floating_hair, hair accessories.\n"
        "Rule 8 (Body Anatomy & Proportions): Body type (hourglass_figure, curvy, slender, athletic, thick_thighs), breast size, collarbone, navel.\n"
        "Rule 9 (Species & Special Traits): Animal ears, tail, horns, wings, fangs, elf_ears, halo if appropriate.\n"
        "Rule 10 (Layered Costume Breakdown): Exhaustive breakdown of clothing layer by layer (innerwear, top, outerwear, bottoms, legwear, footwear).\n"
        "Rule 11 (Fabrics & Textures): Specific materials and trims (leather, silk, denim, lace, gold_trim, sheer, glossy).\n"
        "Rule 12 (Accessories & Props): Jewelry, choker, necklace, gloves, belts, ribbons, held items, signature weapons.\n"
        "Rule 13 (Framing & Camera Perspective): Shot framing (cowboy_shot, upper_body, full_body, portrait) and camera angles (dynamic_angle, low_angle).\n"
        "Rule 14 (Pose & Physical Action): Specific dynamic pose, body positioning, hand gestures (standing, kneeling, sitting, arching, hand_on_hip).\n"
        "Rule 15 (Environment, Lighting & Format): Setting details, time of day, cinematic lighting (rim_lighting, volumetric_lighting, glowing, particles). Output ONLY a single line of lowercase, comma-separated Danbooru tags with underscores for multi-word tags. No markdown, no commentary, no backticks."
    )

    models_to_try = [
        "antigravity/gemini-3.7-flash-high",
        OMNIROUTE_TEXT_MODEL
    ]

    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,
            "max_tokens": 1500
        }
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                OMNIROUTE_URL,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OMNIROUTE_KEY}"
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                cleaned = _clean_tag_response(content)
                if cleaned:
                    low = cleaned.lower()
                    has_girl = "1girl" in low or "2girls" in low or "female" in low
                    has_boy = "1boy" in low or "2boys" in low or "1man" in low or " male" in low or "boy, " in low
                    if not has_girl and not has_boy:
                        cleaned = f"1girl, solo, {cleaned}"
                    elif has_boy and not has_girl and not cleaned.startswith("1boy"):
                        cleaned = f"1boy, solo, {cleaned}"
                    elif has_girl and not has_boy and not cleaned.startswith("1girl"):
                        cleaned = f"1girl, solo, {cleaned}"
                    return cleaned
        except Exception as e:
            print(f"AI enhance_prompt error ({model}): {e}", flush=True)

    return user_prompt
