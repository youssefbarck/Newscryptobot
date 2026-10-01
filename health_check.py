"""
🩺 فحص صحة البوت قبل التشغيل
يفحص: متغيرات البيئة، الاتصال بـ Telegram، صلاحيات القناة، وحدات البوت.
يستدعى من news.yml قبل python main.py في وضع التشخيص.
"""

import os
import sys
import asyncio
import aiohttp


def check_env():
    """فحص متغيرات البيئة الأساسية"""
    print("\n── 1) Environment Variables ──")
    missing = []

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
        print("   ❌ TELEGRAM_BOT_TOKEN مفقود")
    else:
        print(f"   ✅ TELEGRAM_BOT_TOKEN موجود (طوله {len(token)})")

    if not chat_id:
        missing.append("TELEGRAM_CHAT_ID")
        print("   ❌ TELEGRAM_CHAT_ID مفقود")
    else:
        print(f"   ✅ TELEGRAM_CHAT_ID = {chat_id}")

    return len(missing) == 0


async def check_telegram():
    """فحص الاتصال بـ Telegram API"""
    print("\n── 2) Telegram API ──")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("   ⚠️ تخطي (متغيرات مفقودة)")
        return False

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            # getMe
            async with s.get(f"https://api.telegram.org/bot{token}/getMe") as r:
                data = await r.json()
                if data.get("ok"):
                    bot = data["result"]
                    print(f"   ✅ البوت: @{bot.get('username', '?')}")
                else:
                    print(f"   ❌ getMe فشل: {data.get('description', '?')}")
                    return False

            # getChat
            async with s.get(f"https://api.telegram.org/bot{token}/getChat",
                             params={"chat_id": chat_id}) as r:
                data = await r.json()
                if data.get("ok"):
                    chat = data["result"]
                    print(f"   ✅ القناة: {chat.get('title', '?')} (type={chat.get('type', '?')})")
                else:
                    print(f"   ❌ getChat فشل: {data.get('description', '?')}")
                    return False

            # getChatMember
            async with s.get(f"https://api.telegram.org/bot{token}/getChatMember",
                             params={"chat_id": chat_id, "user_id": bot["id"]}) as r:
                data = await r.json()
                if data.get("ok"):
                    member = data["result"]
                    status = member.get("status", "?")
                    print(f"   ✅ حالة البوت في القناة: {status}")
                    if status != "administrator":
                        print("   ⚠️ البوت ليس أدمن — قد لا يستطيع النشر")
                else:
                    print(f"   ⚠️ getChatMember: {data.get('description', '?')}")
        return True
    except Exception as e:
        print(f"   ❌ خطأ اتصال: {e}")
        return False


def check_modules():
    """فحص استيراد وحدات البوت"""
    print("\n── 3) Module Imports ──")
    try:
        from config import TELEGRAM_BOT_TOKEN, RSS_SOURCES, CHANNEL_TAG
        print(f"   ✅ config.py: {len(RSS_SOURCES)} مصدر، tag={CHANNEL_TAG}")
        from sources import fetch_all_news
        print("   ✅ sources.py")
        from translator import google_translate
        print("   ✅ translator.py")
        from formatter import format_post
        print("   ✅ formatter.py")
        from dedup import load_hashes, save_hashes
        print("   ✅ dedup.py")
        from bot import run_cycle
        print("   ✅ bot.py")
        return True
    except Exception as e:
        print(f"   ❌ فشل الاستيراد: {e}")
        return False


async def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║        🔍 Bot Health Check — Pre-Run             ║")
    print("╚══════════════════════════════════════════════════╝")

    ok_env = check_env()
    ok_mod = check_modules()
    ok_tg = await check_telegram() if ok_env else False

    print("\n── Summary ──")
    print(f"   Env:     {'✅' if ok_env else '❌'}")
    print(f"   Modules: {'✅' if ok_mod else '❌'}")
    print(f"   Telegram: {'✅' if ok_tg else '❌'}")

    if not (ok_env and ok_mod and ok_tg):
        print("\n⚠️ يوجد مشاكل — راجع الأخطاء أعلاه")
        sys.exit(1)
    print("\n✅ كل شيء جاهز — يمكن تشغيل البوت")


if __name__ == "__main__":
    asyncio.run(main())
