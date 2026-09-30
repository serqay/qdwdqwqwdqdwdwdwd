import json
import re
import urllib.request
import urllib.parse
import urllib.error
import uuid
import time

def strip_html_tags(text):
    if not text:
        return ""
    return re.sub(r'<[^>]*>', '', str(text))

def api_call(token, method, data=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if data:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=encoded)
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            err_data = json.loads(body)
            desc = err_data.get("description", "")
            if "message is not modified" in desc:
                return {"ok": True, "result": True, "description": desc}
            print(f"Telegram API HTTPError {method}: {err_data}", flush=True)
            return err_data
        except Exception:
            return None
    except Exception as e:
        print(f"Telegram API Error {method}: {e}", flush=True)
        return None

def send_message(token, chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    res = api_call(token, "sendMessage", payload)
    if (not res or not res.get("ok")) and parse_mode:
        desc = (res.get("description") if res else "") or ""
        if "can't parse entities" in desc:
            payload["text"] = strip_html_tags(text)
            payload.pop("parse_mode", None)
            res = api_call(token, "sendMessage", payload)
    return res

def edit_message(token, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    res = api_call(token, "editMessageText", payload)
    if (not res or not res.get("ok")) and parse_mode:
        desc = (res.get("description") if res else "") or ""
        if "can't parse entities" in desc:
            payload["text"] = strip_html_tags(text)
            payload.pop("parse_mode", None)
            res = api_call(token, "editMessageText", payload)
    return res

def send_photo(token, chat_id, image_bytes, caption="", reply_markup=None, parse_mode="HTML", retries=2):
    boundary = f"----FormBoundary{uuid.uuid4().hex}"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    body.extend(str(chat_id).encode("utf-8"))
    body.extend(b"\r\n")

    if caption:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
        body.extend(caption.encode("utf-8"))
        body.extend(b"\r\n")
        if parse_mode:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(b'Content-Disposition: form-data; name="parse_mode"\r\n\r\n')
            body.extend(parse_mode.encode("utf-8"))
            body.extend(b"\r\n")

    if reply_markup:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="reply_markup"\r\n\r\n')
        body.extend(json.dumps(reply_markup).encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="photo"; filename="gen.png"\r\nContent-Type: image/png\r\n\r\n')
    body.extend(image_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                print(f"Error sending photo (HTTPError): {err_data}", flush=True)
                if parse_mode and "can't parse entities" in err_data.get("description", ""):
                    return send_photo(token, chat_id, image_bytes, caption=strip_html_tags(caption), reply_markup=reply_markup, parse_mode=None, retries=0)
            except Exception:
                pass
            if attempt < retries:
                time.sleep(2)
                continue
            return False
        except Exception as e:
            print(f"Error sending photo (Attempt {attempt+1}): {e}", flush=True)
            if attempt < retries:
                time.sleep(2)
                continue
            return False

def get_file(token, file_id):
    res = api_call(token, "getFile", {"file_id": file_id})
    if res and res.get("ok"):
        return res["result"].get("file_path")
    return None

def download_file(token, file_path):
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        print(f"Error downloading file: {e}", flush=True)
        return None
