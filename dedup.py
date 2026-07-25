"""
🔒 dedup.py — منع تكرار الأخبار المُرسلة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
استراتيجية مزدوجة:
  - التحميل: ملف الريبو ← Gist (fallback)
  - الحفظ:  ملف الريبو + git push ← Gist (fallback)
"""

import os, json, subprocess, time, logging

import requests

log = logging.getLogger("NewsBot")

_FILE = "sent_news.json"
_MAX = 2000


def _path():
    return os.path.join(os.getcwd(), _FILE)


def _gist_get() -> set:
    """محاولة تحميل الهاشات من Gist"""
    token = os.environ.get("GITHUB_TOKEN", "")
    gist_id = os.environ.get("GIST_ID_SENT_NEWS", "")
    if not token or not gist_id:
        return set()
    try:
        r = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=10,
        )
        if r.status_code == 200:
            content = r.json().get("files", {}).get("sent_news.json", {}).get("content", "")
            if content:
                return set(json.loads(content).get("hashes", []))
    except Exception as e:
        log.warning(f"🔒 Gist load error: {e}")
    return set()


def _gist_save(hashes: set):
    """محاولة حفظ الهاشات في Gist"""
    token = os.environ.get("GITHUB_TOKEN", "")
    gist_id = os.environ.get("GIST_ID_SENT_NEWS", "")
    if not token or not gist_id:
        return False
    try:
        content = json.dumps({"hashes": list(hashes)[-_MAX:]}, ensure_ascii=False)
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={"files": {"sent_news.json": {"content": content}}},
            timeout=15,
        )
        if r.status_code == 200:
            log.info(f"🔒 Gist: saved {len(hashes)} hashes")
            return True
        log.warning(f"🔒 Gist save failed: HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"🔒 Gist save error: {e}")
    return False


# ═══════════════════════════════════════════════
# API العام
# ═══════════════════════════════════════════════

def load() -> set:
    """تحميل الهاشات: ملف الريبو ← Gist"""
    merged = set()

    # (1) ملف الريبو (عند checkout يوصلنا)
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            loaded = set(data.get("hashes", []))
            if loaded:
                merged.update(loaded)
                print(f"  ✅ Repo file: {len(loaded)} hashes")
    except Exception:
        pass

    # (2) Gist (fallback أو دمج)
    gist_hashes = _gist_get()
    if gist_hashes:
        before = len(merged)
        merged.update(gist_hashes)
        print(f"  ✅ Gist: {len(gist_hashes)} hashes" + (f" ({len(merged) - before} new)" if len(merged) > before else ""))

    print(f"📊 Dedup: {len(merged)} total loaded")
    return merged


def is_sent(hashes_set: set, news_hash: str) -> bool:
    return news_hash in hashes_set


def mark_sent(hashes_set: set, news_hash: str):
    hashes_set.add(news_hash)


def save_to_repo(hashes: set):
    """
    حفظ مزدوج:
    1. git add + commit + push (الطريقة الأساسية)
    2. Gist (بديل)
    """
    # أول شي: حفظ محلي
    try:
        content = json.dumps(
            {"hashes": list(hashes)[-_MAX:], "last_updated": time.time()},
            ensure_ascii=False, indent=2,
        )
        with open(_path(), "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"⚠️ Local save error: {e}")

    # (1) git commit + push
    pushed = False
    if os.environ.get("GITHUB_ACTIONS") == "true":
        try:
            subprocess.run(["git", "config", "user.name", "news-bot[bot]"],
                           capture_output=True, check=True, timeout=10)
            subprocess.run(["git", "config", "user.email", "news-bot[bot]@users.noreply.github.com"],
                           capture_output=True, check=True, timeout=10)

            subprocess.run(["git", "add", _FILE],
                           capture_output=True, check=True, timeout=10)

            result = subprocess.run(["git", "status", "--porcelain", _FILE],
                                   capture_output=True, text=True, timeout=10)
            if result.stdout.strip():
                subprocess.run(
                    ["git", "commit", "-m", f"🔒 dedup: {len(hashes)} hashes"],
                    capture_output=True, check=True, timeout=15,
                )
                subprocess.run(["git", "push"],
                               capture_output=True, check=True, timeout=30)
                pushed = True
                print(f"💾 Repo: committed + pushed {len(hashes)} hashes")
            else:
                pushed = True
                print(f"💾 Repo: no new changes")
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if e.stderr else ""
            print(f"⚠️ Git push failed: {stderr[:200]}")
        except Exception as e:
            print(f"⚠️ Git error: {e}")

    # (2) Gist كبديل أو تأكيد
    if not pushed or True:  # دائماً يحفظ في Gist أيضاً
        _gist_save(hashes)

    print(f"💾 Dedup: {len(hashes)} hashes saved")