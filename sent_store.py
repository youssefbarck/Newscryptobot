"""
💾 sent_store.py — ذاكرة الأخبار المُرسلة (مستقل ومضمون)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
يُحمّل من Gist عند البدء ويحفظ فيه عند الانتهاء.
لا يعتمد على أي global state خارجي.
"""

import os, json, requests

_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GIST_ID = os.environ.get("GIST_ID_SENT_NEWS", "")
_FILE_PATH = os.path.join(os.getcwd(), "sent_news.json")

_hashes: set = set()


def load():
    """تحميل الهاشات من Gist ثم الملف المحلي"""
    global _hashes
    merged = set()

    # (1) Gist
    if _GITHUB_TOKEN and _GIST_ID:
        try:
            r = requests.get(
                f"https://api.github.com/gists/{_GIST_ID}",
                headers={
                    "Authorization": f"token {_GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=10,
            )
            if r.status_code == 200:
                files = r.json().get("files", {})
                if "sent_news.json" in files:
                    content = files["sent_news.json"].get("content", "")
                    if content:
                        loaded = set(json.loads(content).get("hashes", []))
                        if loaded:
                            merged.update(loaded)
                            print(f"  ✅ Gist: {len(loaded)} hashes")
        except Exception as e:
            print(f"  ⚠️ Gist load error: {e}")

    # (2) ملف محلي (fallback)
    try:
        with open(_FILE_PATH, "r") as f:
            loaded = set(json.load(f).get("hashes", []))
            if loaded:
                merged.update(loaded)
                print(f"  ✅ Local file: {len(loaded)} hashes")
    except Exception:
        pass

    # دمج
    if merged:
        _hashes = merged

    print(f"📊 Sent store: {len(_hashes)} hashes loaded")


def is_sent(news_hash: str) -> bool:
    """هل الخبر أُرسل سابقاً؟"""
    return news_hash in _hashes


def mark_sent(news_hash: str):
    """تسجيل خبر كمُرسَل"""
    _hashes.add(news_hash)


def save():
    """حفظ الهاشات في الملف المحلي + Gist"""
    content = json.dumps({"hashes": list(_hashes)[-500:]})

    # ملف محلي (دائماً)
    try:
        with open(_FILE_PATH, "w") as f:
            f.write(content)
    except Exception:
        pass

    # Gist
    if _GITHUB_TOKEN and _GIST_ID:
        try:
            r = requests.patch(
                f"https://api.github.com/gists/{_GIST_ID}",
                headers={
                    "Authorization": f"token {_GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                },
                json={"files": {"sent_news.json": {"content": content}}},
                timeout=10,
            )
            if r.status_code == 200:
                print(f"💾 Saved {len(_hashes)} hashes → Gist")
            else:
                print(f"⚠️ Gist save failed: HTTP {r.status_code}")
        except Exception as e:
            print(f"⚠️ Gist save error: {e}")
    else:
        print(f"💾 Saved {len(_hashes)} hashes → local file")