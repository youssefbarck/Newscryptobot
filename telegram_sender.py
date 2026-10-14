# -*- coding: utf-8 -*-
"""إرسال الرسائل إلى تيليجرام — صورة الخبر إن وجدت وإلا نص منسق.

بلا روابط: لا زر «اقرأ الخبر» ولا أي رابط مصدر — صورة جذابة وخبر احترافي فقط.
"""
import logging
import re
import time
from pathlib import Path

import requests

from .config import REQUEST_TIMEOUT

log = logging.getLogger("crypto-bot")

# وكيل متصفح كامل — بعض مواقع الأخبار ترفض الطلبات بدون UA حقيقي
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# بصمات الأنواع المقبولة في sendPhoto (JPG / PNG / WEBP)
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # يُدقق لاحقًا أن البايتات 8-11 هي WEBP
)


def _sniff_mime(data: bytes) -> str | None:
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


def download_image(url: str, max_bytes: int = 9_500_000) -> tuple[bytes, str] | None:
    """تحميل صورة الخبر والتحقق أنها صورة حقيقية صالحة لتيليجرام.

    يُرجع (البيانات، نوع MIME) أو None عند الفشل — لا يُرفع أي استثناء.
    """
    if not url or not url.startswith("http"):
        return None
    try:
        r = requests.get(url, headers=BROWSER_HEADERS,
                         timeout=REQUEST_TIMEOUT, stream=True, allow_redirects=True)
        if not r.ok:
            log.info("🖼 صورة غير متاحة (%s): %s", r.status_code, url[:90])
            return None
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "image" not in ctype and "octet-stream" not in ctype:
            log.info("🖼 ليست صورة (%s): %s", ctype or "?", url[:90])
            return None
        data = r.raw.read(max_bytes + 1) if r.raw else b""
        if not data:
            data = r.content
        if len(data) > max_bytes:
            log.info("🖼 صورة أكبر من الحد المسموح — تجاهل: %s", url[:90])
            return None
        if len(data) < 3_000:  # أصغر من أي صورة خبر حقيقية — غالبًا صفحة خطأ
            return None
        mime = _sniff_mime(data)
        if not mime:
            log.info("🖼 نوع ملف غير مدعوم (ليس JPG/PNG/WEBP): %s", url[:90])
            return None
        return data, mime
    except requests.RequestException as exc:
        log.info("🖼 فشل تحميل الصورة: %s", exc)
        return None


def _load_photo(image: str) -> tuple[bytes, str] | None:
    """يقبل رابط صورة (http) أو مسار ملف محلي (صور البديل الجاهزة)."""
    if not image:
        return None
    if image.startswith("http"):
        return download_image(image)
    try:
        p = Path(image)
        if p.exists() and p.stat().st_size > 100:
            ext = p.suffix.lower()
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}.get(ext)
            if mime:
                return p.read_bytes(), mime
    except OSError:
        pass
    return None


def verify_credentials(token: str, chat_id: str) -> tuple[bool, str]:
    """فحص تشخيصي مسبق: صلاحية التوكن ثم إمكانية الوصول للمحادثة.

    يُرجع (نجاح، رسالة خطأ عربية واضحة إن فشل).
    """
    if not token:
        return False, "❌ TELEGRAM_BOT_TOKEN فارغ — أضِفه في Secrets"
    if not chat_id:
        return False, "❌ TELEGRAM_CHAT_ID فارغ — أضِفه في Secrets"

    # 1) التوكن صالح؟
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe",
                         timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403):
            return False, ("❌ التوكن غير صالح (401) — افتح @BotFather "
                           "وانسخ التوكن كاملًا من جديد")
        if not r.ok:
            return False, f"❌ فحص التوكن فشل ({r.status_code}) — تحقق من قيمته"
        bot_name = (r.json() or {}).get("result", {}).get("username") or "?"
        log.info("✔ التوكن سليم — البوت: @%s", bot_name)
    except requests.RequestException as exc:
        return False, f"❌ لا يمكن الوصول إلى تيليجرام: {exc}"

    # 2) المحادثة موجودة والبوت عضو فيها؟
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getChat",
                         params={"chat_id": chat_id}, timeout=REQUEST_TIMEOUT)
        if not r.ok:
            desc = ""
            try:
                desc = (r.json() or {}).get("description", "")
            except Exception:
                pass
            return False, (
                f"❌ تعذر الوصول إلى المحادثة «{chat_id}» — {desc}\n"
                "   الحلول الأكثر شيوعًا:\n"
                "   1️⃣ القنوات الخاصة معرّفها يبدأ بـ -100 (وليس رقمًا موجبًا)\n"
                "   2️⃣ أضِف البوت مشرفًا (Admin) في القناة\n"
                "   3️⃣ القنوات العامة اكتبها مثل @mychannel")
        title = (r.json() or {}).get("result", {}).get("title") or chat_id
        log.info("✔ المحادثة متاحة: %s", title)
    except requests.RequestException as exc:
        return False, f"❌ خطأ اتصال أثناء فحص المحادثة: {exc}"

    return True, ""


def _post(token: str, method: str, payload: dict, files: dict | None = None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        r = requests.post(url, data=payload, files=files, timeout=REQUEST_TIMEOUT + 40)
    else:
        r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 429:  # تجاوز الحد — انتظر وأعد المحاولة مرة واحدة
        retry_after = 2
        try:
            retry_after = int(r.json().get("parameters", {}).get("retry_after", 2))
        except Exception:
            pass
        time.sleep(retry_after + 1)
        if files:
            r = requests.post(url, data=payload, files=files,
                              timeout=REQUEST_TIMEOUT + 40)
        else:
            r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    return r


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def send_news(token: str, chat_id: str, html_text: str,
              image: str | None = None) -> bool:
    """إرسال خبر واحد — صورة + خبر احترافي، بلا أي روابط.

    image: رابط صورة الخبر أو مسار صورة بديلة محلية.
    يُرجع True عند النجاح.
    """
    # المحاولة الأولى: صورة محمّلة كمرفق (تتجاوز حجب الروابط والهوتلينك)
    photo = _load_photo(image)
    if photo:
        data, mime = photo
        ext = {"image/jpeg": "news.jpg", "image/png": "news.png",
               "image/webp": "news.webp"}[mime]
        payload = {
            "chat_id": chat_id,
            "caption": html_text[:1024],
            "parse_mode": "HTML",
        }
        try:
            r = _post(token, "sendPhoto", payload,
                      files={"photo": (ext, data, mime)})
            if r.ok:
                return True
            log.warning("sendPhoto رفض الرفع (%s) — محاولة بالرابط ثم نص",
                        r.status_code)
        except requests.RequestException as exc:
            log.warning("sendPhoto خطأ اتصال أثناء الرفع: %s", exc)

        # المحاولة الثانية: تمرير الرابط مباشرة لتيليجرام (قد ينجح من سيرفراته)
        if image and image.startswith("http"):
            try:
                r = _post(token, "sendPhoto", {**payload, "photo": image})
                if r.ok:
                    return True
            except requests.RequestException:
                pass

    # المحاولة الثالثة: نص HTML
    payload = {
        "chat_id": chat_id,
        "text": html_text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = _post(token, "sendMessage", payload)
        if r.ok:
            return True
        # وسوم HTML تالفة؟ أرسل نصًا مجردًا كحل أخير
        if r.status_code == 400:
            payload.pop("parse_mode", None)
            payload["text"] = _strip_tags(html_text)[:4096]
            return _post(token, "sendMessage", payload).ok
        log.error("فشل الإرسال %s: %s", r.status_code, r.text[:200])
        return False
    except requests.RequestException as exc:
        log.error("خطأ اتصال بتيليجرام: %s", exc)
        return False
