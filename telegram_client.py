# -*- coding: utf-8 -*-
"""📤 إرسال الرسائل إلى تيليجرام — صورة مرفوعة كمرفق + خبر احترافي.

بلا روابط نهائيًا: لا زر «اقرأ الخبر» ولا أي رابط مصدر —
صورة جذابة وخبر احترافي فقط.
"""
import logging
import re

import aiohttp

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger("NewsBot")

API = "https://api.telegram.org"


def check_config() -> tuple[bool, str]:
    """التحقق من وجود بيانات تيليجرام."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        return False, "❌ متغيرات ناقصة: " + ", ".join(missing) + " — أضِفها في Secrets"
    return True, ""


async def verify_credentials(session: aiohttp.ClientSession) -> tuple[bool, str]:
    """فحص تشخيصي مسبق: التوكن ثم المحادثة ثم حالة البوت داخلها.

    يُرجع (نجاح، رسالة خطأ عربية واضحة إن فشل).
    """
    ok, err = check_config()
    if not ok:
        return False, err

    # 1) التوكن صالح؟
    try:
        async with session.get(f"{API}/bot{TELEGRAM_BOT_TOKEN}/getMe",
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json(content_type=None)
            if resp.status in (401, 403) or not data.get("ok"):
                return False, ("❌ التوكن غير صالح — افتح @BotFather "
                               "وانسخ التوكن كاملًا من جديد")
            bot_id = data["result"]["id"]
            bot_name = data["result"].get("username") or "?"
            log.info("✔ التوكن سليم — البوت: @%s", bot_name)
    except Exception as exc:
        return False, f"❌ لا يمكن الوصول إلى تيليجرام: {exc}"

    # 2) المحادثة موجودة والبوت عضو فيها؟
    try:
        async with session.get(f"{API}/bot{TELEGRAM_BOT_TOKEN}/getChat",
                               params={"chat_id": TELEGRAM_CHAT_ID},
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json(content_type=None)
            if not data.get("ok"):
                desc = data.get("description", "")
                return False, (
                    f"❌ تعذر الوصول إلى المحادثة «{TELEGRAM_CHAT_ID}» — {desc}\n"
                    "   الحلول الأكثر شيوعًا:\n"
                    "   1️⃣ القنوات الخاصة معرّفها يبدأ بـ -100 (وليس رقمًا موجبًا)\n"
                    "   2️⃣ أضِف البوت مشرفًا (Admin) في القناة\n"
                    "   3️⃣ القنوات العامة اكتبها مثل @mychannel")
            title = data["result"].get("title") or TELEGRAM_CHAT_ID
            log.info("✔ المحادثة متاحة: %s", title)
    except Exception as exc:
        return False, f"❌ خطأ اتصال أثناء فحص المحادثة: {exc}"

    # 3) البوت مشرف في القناة؟ (فحص معمّق — من health_check القديم)
    try:
        async with session.get(
                f"{API}/bot{TELEGRAM_BOT_TOKEN}/getChatMember",
                params={"chat_id": TELEGRAM_CHAT_ID, "user_id": bot_id},
                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json(content_type=None)
            if data.get("ok"):
                status = data["result"].get("status", "?")
                log.info("✔ حالة البوت في القناة: %s", status)
                if status != "administrator":
                    log.warning("⚠️ البوت ليس مشرفًا — قد يُرفض النشر")
            else:
                log.warning("⚠️ getChatMember: %s", data.get("description", "?"))
    except Exception:
        pass

    return True, ""


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def send_post(session: aiohttp.ClientSession, text: str,
                    photo: tuple[bytes, str] | None = None,
                    photo_name: str = "news.jpg") -> bool:
    """إرسال منشور واحد: صورة مرفوعة كمرفق + نص، أو نص فقط عند الفشل.

    بلا reply_markup وبلا أي روابط — يُرجع True عند النجاح.
    """
    if not text:
        return False

    # المحاولة الأولى: رفع الصورة كمرفق حقيقي (يتجاوز الحجب والهوتلينك)
    if photo:
        data, mime = photo
        form = aiohttp.FormData()
        form.add_field("chat_id", TELEGRAM_CHAT_ID)
        form.add_field("caption", text[:1024])
        form.add_field("parse_mode", "HTML")
        form.add_field("photo", data, filename=photo_name, content_type=mime)
        try:
            async with session.post(f"{API}/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                                    data=form,
                                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    return True
                body = await resp.text()
                log.warning("📸 sendPhoto رفض (%s): %s — التراجع إلى نص",
                            resp.status, body[:150])
                if resp.status == 429:
                    try:
                        import json as _json
                        retry = (_json.loads(body).get("parameters") or {}).get("retry_after", 3)
                        import asyncio as _aio
                        await _aio.sleep(int(retry) + 1)
                    except Exception:
                        await _aio.sleep(4)
                    # إعادة محاولة واحدة بعد الانتظار
                    form = aiohttp.FormData()
                    form.add_field("chat_id", TELEGRAM_CHAT_ID)
                    form.add_field("caption", text[:1024])
                    form.add_field("parse_mode", "HTML")
                    form.add_field("photo", data, filename=photo_name, content_type=mime)
                    async with session.post(
                            f"{API}/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", data=form,
                            timeout=aiohttp.ClientTimeout(total=60)) as resp2:
                        if resp2.status == 200:
                            return True
        except Exception as exc:
            log.warning("📸 sendPhoto خطأ: %s", exc)

    # المحاولة الثانية: نص HTML
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096],
               "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        async with session.post(f"{API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                json=payload,
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                return True
            # وسوم HTML تالفة؟ نص مجرد كحل أخير
            if resp.status == 400:
                payload.pop("parse_mode", None)
                payload["text"] = _strip_tags(text)[:4096]
                async with session.post(
                        f"{API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)) as resp2:
                    return resp2.status == 200
            body = await resp.text()
            log.error("❌ فشل الإرسال %s: %s", resp.status, body[:200])
            return False
    except Exception as exc:
        log.error("❌ خطأ اتصال بتيليجرام: %s", exc)
        return False
