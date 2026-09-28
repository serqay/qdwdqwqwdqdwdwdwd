import re
import json
import urllib.request
import urllib.parse

def is_cyrillic(text):
    return bool(re.search(r'[а-яА-ЯёЁ]', str(text)))

def search_online_characters(query):
    if not query or is_cyrillic(query):
        return []
    results = []
    encoded = urllib.parse.quote(query.lower().strip())
    try:
        url = f"https://danbooru.donmai.us/tags.json?search[name_matches]=*{encoded}*&search[category]=4&search[order]=count&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "GummyFluxBot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            tags = json.loads(r.read().decode("utf-8"))
            for t in tags:
                clean_name = t["name"].replace("_", " ")
                results.append((clean_name, t["name"]))
    except Exception:
        pass

    try:
        url = f"https://e621.net/tags.json?search[name_matches]=*{encoded}*&search[category]=4&search[order]=count&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "GummyFluxBot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            tags = json.loads(r.read().decode("utf-8"))
            for t in tags:
                clean_name = t["name"].replace("_", " ")
                if not any(r[1] == t["name"] for r in results):
                    results.append((clean_name, t["name"]))
    except Exception:
        pass

    return results[:6]

def search_online_poses(query):
    if not query or is_cyrillic(query):
        return []
    results = []
    encoded = urllib.parse.quote(query.lower().strip())
    try:
        url = f"https://danbooru.donmai.us/tags.json?search[name_matches]=*{encoded}*&search[category]=0&search[order]=count&limit=6"
        req = urllib.request.Request(url, headers={"User-Agent": "GummyFluxBot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            tags = json.loads(r.read().decode("utf-8"))
            for t in tags:
                clean_name = t["name"].replace("_", " ")
                results.append((clean_name, t["name"]))
    except Exception:
        pass
    return results[:6]

def search_online_environment(query):
    if not query or is_cyrillic(query):
        return []
    results = []
    encoded = urllib.parse.quote(query.lower().strip())
    try:
        url = f"https://danbooru.donmai.us/tags.json?search[name_matches]=*{encoded}*&search[category]=0&search[order]=count&limit=6"
        req = urllib.request.Request(url, headers={"User-Agent": "GummyFluxBot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            tags = json.loads(r.read().decode("utf-8"))
            for t in tags:
                clean_name = t["name"].replace("_", " ")
                results.append((clean_name, t["name"]))
    except Exception:
        pass
    return results[:6]
