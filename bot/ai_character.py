import base64
import json
import re
import urllib.request

from bot.config import (
    OMNIROUTE_URL,
    OMNIROUTE_KEY,
    OMNIROUTE_TEXT_MODEL,
    OMNIROUTE_VISION_MODEL,
)


def _call_ai(model, messages, max_tokens=900, timeout=35):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        OMNIROUTE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OMNIROUTE_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)

    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("ИИ вернул пустой ответ")
    return content.strip()


def _clean_tags(raw, max_tags=45):
    """Очистка формата, без угадывания пола или добавления новых деталей."""
    if not raw:
        return ""

    text = str(raw).strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^(?:tags|danbooru tags|result|output)\s*:\s*", "",
                  text, flags=re.IGNORECASE)

    result = []
    seen = set()

    for item in re.split(r"[,\n]+", text):
        tag = item.strip().strip("\"'` ").lower()
        if not tag:
            continue

        # Не пропускаем пояснения вместо тегов.
        if tag.startswith(("here are", "here is", "note:", "i cannot",
                           "i can't", "as an ai")):
            continue

        # Многословные теги для используемого формата промптов.
        tag = re.sub(r"\s+", "_", tag)

        # Скобки внутри тега персонажа экранируем для WebUI.
        tag = re.sub(r"(?<!\\)\(", r"\(", tag)
        tag = re.sub(r"(?<!\\)\)", r"\)", tag)

        if len(tag) > 100 or tag in seen:
            continue

        seen.add(tag)
        result.append(tag)
        if len(result) >= max_tags:
            break

    return ", ".join(result)


def _text_models():
    # Не делаем два одинаковых обращения, если модель в конфиге совпадает.
    return list(dict.fromkeys([
        OMNIROUTE_TEXT_MODEL,
        "antigravity/gemini-3.7-flash-high",
    ]))


def describe_character_by_name(char_name):
    name = (char_name or "").strip()
    if not name:
        return ""

    norm_name = re.sub(r"[\s_]+", " ", name.lower())
    if "homdan" in norm_name:
        return (
            "1boy, solo, homdan \\(minecraft\\), dark_skin, "
            "bear_ears, brown_hair, short_curly_hair, "
            "black_mouth_mask, blue_hoodie, white_shirt"
        )

    system = (
        "You write concise visual character tags for anime image generation. "
        "Return ONLY one line of lowercase comma-separated tags. "
        "Describe stable canonical appearance: exact character/series tag IF known, "
        "subject count IF known, skin, hair, eyes, distinctive clothing and accessories. "
        "Do NOT invent unknown features. Do NOT add pose, camera framing, gaze, "
        "facial expression, environment, lighting, body proportions, quality tags "
        "or an unrelated outfit. Do NOT default to 1girl. "
        "If you do not recognize the character, return only a conservative "
        "name tag without invented appearance. Multiword tags use underscores."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Character: {name[:180]}"},
    ]

    for model in _text_models():
        try:
            tags = _clean_tags(_call_ai(model, messages))
            if tags:
                return tags
        except Exception as exc:
            print(f"describe_character_by_name ({model}): {exc}", flush=True)

    # При недоступности ИИ не выдаём придуманную внешность за достоверную.
    fallback = re.sub(r"[^\w\s()\-:]", "", name.lower()).strip()
    return _clean_tags(fallback, max_tags=1)


def _image_mime(image_bytes):
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Поддерживаются JPEG, PNG и WebP")


def _parse_photo_response(content):
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    # Ожидаемый ответ — JSON. Небольшой запас на текст вокруг объекта.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("ИИ не вернул JSON с описанием фотографии")
        data = json.loads(match.group())

    name = str(data.get("name") or "Персонаж по фото").strip()[:100]
    raw_tags = data.get("tags", [])
    if isinstance(raw_tags, list):
        raw_tags = ", ".join(str(t) for t in raw_tags)
    tags = _clean_tags(raw_tags)

    if not tags:
        raise ValueError("ИИ не обнаружил пригодных тегов на изображении")

    return name, tags


def describe_character_by_photo(image_bytes):
    """При ошибке возвращает (None, '') и не подменяет персонажа."""
    try:
        if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
            raise ValueError("Изображение пустое или больше 10 МБ")

        mime = _image_mime(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")

        instructions = (
            "Analyze the attached image for anime image generation. "
            "Return ONLY valid JSON: "
            '{"name":"recognized character and series OR Персонаж по фото",'
            '"tags":["tag1","tag2"]}. '
            "Use lowercase booru-like visual tags with underscores. "
            "Describe ONLY features actually visible: number of subjects when clear, "
            "hair, eyes when visible, skin/fur, distinctive clothes, accessories, "
            "visible pose and framing. Do NOT guess hidden body parts, eye color "
            "behind a blindfold, character identity, gender, series, materials "
            "or details outside the image. Do NOT default to 1girl. "
            "Do not add style, quality, lighting or unrelated environment tags. "
            "Prefer 15–35 useful tags over an exhaustive list."
        )

        content = _call_ai(
            OMNIROUTE_VISION_MODEL,
            [{
                "role": "user",
                "content": [
                    {"type": "text", "text": instructions},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{encoded}"
                        },
                    },
                ],
            }],
            max_tokens=900,
            timeout=50,
        )
        return _parse_photo_response(content)
    except Exception as exc:
        print(f"describe_character_by_photo: {exc}", flush=True)
        return None, ""


def enhance_prompt_with_ai(user_prompt):
    raw = (user_prompt or "").strip()
    if not raw:
        return ""

    system = (
        "Convert the user's image request to one line of concise, "
        "lowercase, comma-separated booru-style tags. "
        "Preserve the requested subject count, identity, clothing, action, "
        "framing and setting. Never invent gender, nudity, a second person, "
        "sexual action, body proportions or a character franchise. "
        "Do not replace a specified pose, outfit or camera angle. "
        "If something is unspecified, leave it unspecified. "
        "Prefer 15–40 relevant tags. Multiword tags use underscores. "
        "Return tags only, without explanations or markdown."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": raw[:2000]},
    ]

    for model in _text_models():
        try:
            tags = _clean_tags(_call_ai(model, messages), max_tags=50)
            if tags:
                return tags
        except Exception as exc:
            print(f"enhance_prompt_with_ai ({model}): {exc}", flush=True)

    return raw
