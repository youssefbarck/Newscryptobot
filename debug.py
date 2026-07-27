"""
🔍 سكريبت تشخيص شامل — يفحص كل شيء خطوة بخطوة
يُرفض أي مشكلة ويوضحها بوضوح
"""

import os
import sys
import asyncio
import aiohttp
import json
import time

BANNER = """
╔══════════════════════════════════════════════════════════╗
║          🔍 CRYPTO NEWS BOT — FULL DIAGNOSTIC          ║
╚══════════════════════════════════════════════════════════╝
"""

results = []

def log_test(name, passed, detail=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    msg = f"{status} | {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append({"name": name, "passed": passed, "detail": detail})


def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


async def main():
    print(BANNER)

    # ═════════════════════════════════════════
    # 1) فحص متغيرات البيئة
    # ═════════════════════════════════════════
    section("STEP 1: Environment Variables")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    log_test("TELEGRAM_BOT_TOKEN exists",
             bool(token),
             f"length={len(token)}" if token else "EMPTY — أضفه في GitHub Secrets")

    if token:
        log_test("TELEGRAM_BOT_TOKEN format",
                 token.startswith("BOT_TOKEN_HIDDEN"),
                 f"starts with: {token[:10]}...")
        print(f"        Token first 10 chars: {token[:10]}...")

    log_test("TELEGRAM_CHAT_ID exists",
             bool(chat_id),
             f"value={chat_id}" if chat_id else "EMPTY — أضفه في GitHub Secrets")

    if chat_id:
        log_test("TELEGRAM_CHAT_ID format",
                 chat_id.startswith("-100") or chat_id.startswith("@"),
                 f"value={chat_id}")

    if not token or not chat_id:
        print("\n⛔ المتغيرات غير موجودة! تأكد من إضافتها في:")
        print("   GitHub → Settings → Secrets and variables → Actions")
        print("   TELEGRAM_BOT_TOKEN")
        print("   TELEGRAM_CHAT_ID")
        return

    # ═════════════════════════════════════════
    # 2) فحص الاتصال بـ Telegram API
    # ═════════════════════════════════════════
    section("STEP 2: Telegram API Connection")

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # فحص getMe
            url = f"https://api.telegram.org/bot{token}/getMe"
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("ok"):
                    bot_info = data.get("result", {})
                    bot_name = bot_info.get("first_name", "?")
                    bot_user = bot_info.get("username", "?")
                    log_test("Bot getMe", True, f"@{bot_user} ({bot_name})")
                else:
                    err = data.get("description", "Unknown error")
                    log_test("Bot getMe", False, err)
                    return
    except Exception as e:
        log_test("Bot getMe connection", False, str(e))
        return

    # ═════════════════════════════════════════
    # 3) فحص القناة
    # ═════════════════════════════════════════
    section("STEP 3: Channel Access")

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # فحص getChat
            url = f"https://api.telegram.org/bot{token}/getChat"
            params = {"chat_id": chat_id}
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("ok"):
                    chat_info = data.get("result", {})
                    chat_type = chat_info.get("type", "?")
                    chat_title = chat_info.get("title", "?")
                    log_test("getChat", True, f"type={chat_type}, title={chat_title}")
                else:
                    err = data.get("description", "Unknown error")
                    log_test("getChat", False, err)
                    if "not found" in err.lower():
                        print(f"\n   💡 المعرف {chat_id} غير صحيح")
                        print(f"   تأكد من أن القناة عامة وأن المعرف يبدأ بـ -100")
                    return
    except Exception as e:
        log_test("getChat connection", False, str(e))
        return

    # ═════════════════════════════════════════
    # 4) فحص صلاحيات البوت في القناة
    # ═════════════════════════════════════════
    section("STEP 4: Bot Permissions")

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"https://api.telegram.org/bot{token}/getChatMember"
            params = {"chat_id": chat_id, "user_id": bot_info.get("id")}
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("ok"):
                    member = data.get("result", {})
                    status = member.get("status", "?")
                    can_post = member.get("can_post_messages", False)
                    can_edit = member.get("can_edit_messages", False)
                    can_media = member.get("can_post_audios", member.get("can_send_media_messages", False))

                    log_test("Bot member status", status in ["administrator", "member"],
                             f"status={status}")

                    if status == "administrator":
                        log_test("Can post messages", True)
                        log_test("Can send media", True)
                    elif status == "member":
                        log_test("Can post messages",
                                 can_post, f"can_post_messages={can_post}")
                        log_test("Can send media",
                                 can_media, f"can_send_media={can_media}")
                        if not can_post:
                            print("\n   ⚠️ البوت عضو لكن لا يملك صلاحية النشر!")
                            print("   يجب ترقية البوت إلى أدمن")
                    else:
                        print(f"\n   ⚠️ حالة البوت: {status}")
                        print("   يجب إضافة البوت كأدمن في القناة")
                else:
                    err = data.get("description", "Unknown error")
                    log_test("getChatMember", False, err)
    except Exception as e:
        log_test("getChatMember", False, str(e))

    # ═════════════════════════════════════════
    # 5) إرسال رسالة اختبار
    # ═════════════════════════════════════════
    section("STEP 5: Test Message Sending")

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": "🔧 اختبار تشخيص — البوت يعمل!\n\nإذا رأيت هذه الرسالة = كل شيء جاهز ✅",
            }
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("ok"):
                    msg_id = data.get("result", {}).get("message_id", "?")
                    log_test("sendMessage", True, f"message_id={msg_id}")
                    print("\n   🎉 الرسالة وصلت للقناة! يمكنك حذفها يدوياً.")
                else:
                    err = data.get("description", "Unknown error")
                    log_test("sendMessage", False, err)
    except Exception as e:
        log_test("sendMessage", False, str(e))

    # ═════════════════════════════════════════
    # 6) فحص وحدات البوت
    # ═════════════════════════════════════════
    section("STEP 6: Bot Module Imports")

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from config import RSS_SOURCES, PROTECTED_NAMES, CHANNEL_TAG, DEDUP_FILE
        log_test("config.py", True,
                 f"sources={len(RSS_SOURCES)}, names={len(PROTECTED_NAMES)}")
        log_test("DEDUP_FILE path", True, DEDUP_FILE)

        from sources import fetch_all_news, strip_source_from_title, KNOWN_SOURCE_NAMES
        log_test("sources.py", True, f"known_sources={len(KNOWN_SOURCE_NAMES)}")

        from translator import google_translate, _build_protected_entities
        log_test("translator.py", True, "[[N]] placeholder format")

        from formatter import format_post, validate_post, extract_bullets
        log_test("formatter.py", True)

        from dedup import load_hashes, save_hashes, compute_hash
        log_test("dedup.py", True)

        from bot import run_cycle, send_post
        log_test("bot.py", True)

    except ImportError as e:
        log_test("Module import", False, str(e))
    except Exception as e:
        log_test("Module load", False, str(e))

    # ═════════════════════════════════════════
    # 7) فحص جلب RSS
    # ═════════════════════════════════════════
    section("STEP 7: RSS Feed Test (first source only)")

    try:
        from sources import fetch_source
        test_source = {
            "name": "CoinDesk",
            "url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",
            "type": "news",
        }
        connector = aiohttp.TCPConnector(limit=3)
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            connector=connector
        ) as session:
            items = await fetch_source(session, test_source)
            log_test("CoinDesk RSS", len(items) > 0, f"{len(items)} items fetched")
            if items:
                print(f"        First title: {items[0].title[:80]}")
    except Exception as e:
        log_test("CoinDesk RSS", False, str(e))

    # ═════════════════════════════════════════
    # 8) فحص الترجمة
    # ═════════════════════════════════════════
    section("STEP 8: Translation Test")

    try:
        from translator import google_translate
        test = "Bitcoin price reached $100K today"
        translated = await google_translate(test)
        if translated:
            has_btc = "Bitcoin" in translated
            has_price = "$100K" in translated or "100K" in translated
            no_leak = "[[" not in translated and "§" not in translated
            log_test("Translation", True, f'"{translated}"')
            log_test("Entities preserved", has_btc, f"Bitcoin={has_btc}")
            log_test("Price preserved", has_price, f"$100K={has_price}")
            log_test("No placeholder leak", no_leak)
        else:
            log_test("Translation", False, "returned None")
    except Exception as e:
        log_test("Translation", False, str(e))

    # ═════════════════════════════════════════
    # ملخص النتائج
    # ═════════════════════════════════════════
    section("SUMMARY")
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    total = len(results)

    print(f"\n   Total: {total} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print("\n   🎉 كل شيء يعمل! شغّل البوت الرئيسي الآن.")
    else:
        print(f"\n   ⚠️ {failed} مشكلة(s) — راجع التفاصيل أعلاه")
        print("\n   المشاكل التي تحتاج إصلاح:")
        for r in results:
            if not r["passed"]:
                print(f"   ❌ {r['name']}: {r['detail']}")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
