# -*- coding: utf-8 -*-
"""إرسال الرسائل إلى تيليجرام — صورة الخبر إن وجدت وإلا نص منسق"""
import logging
import re
import time

import requests

from .config import REQUEST_TIMEOUT

log = logging.getLogger("crypto-bot")


def _post(token: str, method: str, payload: dict):
    url = f"https://api.telegram.org/bot{token}/{method}"
    r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 429:  # تجاوز الحد — انتظر وأعد المحاولة مرة واحدة
        retry_after = 2
        try:
            retry_after = int(r.json().get("parameters", {}).get("retry_after", 2))
        except Exception:
            pass
        time.sleep(retry_after + 1)
        r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    return r


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def send_news(token: str, chat_id: str, html_text: str, image_url: str | None = None,
              source_url: str | None = None) -> bool:
    """إرسال خبر واحد — يرجّع True عند النجاح."""
    keyboard = None
    if source_url and source_url.startswith("http"):
        keyboard = {"inline_keyboard": [[{"text": "📰 اقرأ الخبر كاملًا", "url": source_url}]]}

    # المحاولة الأولى: صورة + تسمية منسقة (أجمل بكثير للقناة)
    if image_url and image_url.startswith("http"):
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": html_text[:1024],
            "parse_mode": "HTML",
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        try:
            r = _post(token, "sendPhoto", payload)
            if r.ok:
                return True
            log.warning("sendPhoto رفض (%s) — التراجع إلى نص فقط", r.status_code)
        except requests.RequestException as exc:
            log.warning("sendPhoto خطأ اتصال: %s", exc)

    # المحاولة الثانية: نص HTML
    payload = {
        "chat_id": chat_id,
        "text": html_text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard
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
