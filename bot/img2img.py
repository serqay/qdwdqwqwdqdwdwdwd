
def generate_img2img(prompt, init_image_b64, denoising_strength=0.5, is_nsfw=True, width=832, height=1216, is_custom=False, steps=28, model=DEFAULT_MODEL, char_gender="female", cfg_scale=DEFAULT_CFG_SCALE):
    import urllib.request, json, time, base64
    from bot.config import AVAILABLE_MODELS, DEFAULT_MODEL, DEFAULT_CFG_SCALE

    p_low = prompt.lower()
    is_male = char_gender == "male"

    model_info = AVAILABLE_MODELS.get(model, AVAILABLE_MODELS.get(DEFAULT_MODEL, {}))
    lora_name = model_info.get("lora_name")
    lora_weight = model_info.get("lora_weight")
    style_prefix = model_info.get("style_prefix", "")

    from bot.sd_client import filter_clothing_tags
    if is_nsfw and not is_custom:
        if "nude" not in p_low and "naked" not in p_low and "no clothes" not in p_low:
            prompt = f"nude, fully naked, nipples, pussy, bare breasts, uncensored, {prompt}"
        prompt = filter_clothing_tags(prompt)

    prompt = f"{style_prefix}, {prompt}, <lora:{lora_name}:{lora_weight}>"

    neg_prompt = "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, bad feet, censored"
    if is_male:
        neg_prompt += ", female, breasts, girl, woman"
    else:
        neg_prompt += ", penis, male, boy, man, futanari, muscular"

    payload = {
        "prompt": prompt,
        "negative_prompt": neg_prompt,
        "init_images": [init_image_b64],
        "denoising_strength": denoising_strength,
        "steps": steps,
        "width": width,
        "height": height,
        "cfg_scale": cfg_scale,
        "sampler_name": "Euler a",
        "scheduler": "Automatic",
        "override_settings": {
            "sd_model_checkpoint": model_info.get("checkpoint")
        },
        "override_settings_restore_afterwards": False
    }

    url = "http://127.0.0.1:7860/sdapi/v1/img2img"
    start_t = time.time()
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=300) as response:
            resp_data = json.loads(response.read().decode('utf-8'))
            if 'images' in resp_data and len(resp_data['images']) > 0:
                elapsed = round(time.time() - start_t, 1)
                from bot.sd_client import trim_system_memory
                trim_system_memory()
                return base64.b64decode(resp_data['images'][0]), elapsed
    except Exception as e:
        print(f"SD API Img2Img Error: {e}", flush=True)
    return None, 0
