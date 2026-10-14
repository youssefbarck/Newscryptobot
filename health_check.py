# -*- coding: utf-8 -*-
"""
🩺 فحص صحة البوت قبل التشغيل
يفحص: متغيرات البيئة، الوحدات، اتصال Telegram، صلاحية المشرف، أسعار السوق، الصور البديلة.
يستدعى من news.yml قبل python main.py في وضع التشخيص، أو محليًا:
    python health_check.py
"""
import asyncio
import logging
import os
import sys

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("health")


def check_env() -> bool:
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
    for opt in ("CRYPTOPANIC_API_KEY", "COINGECKO_API_KEY", "WHALE_ALERT_API_KEY"):
        if os.environ.get(opt):
            print(f"   ✅ {opt} موجود (اختياري)")
    return len(missing) == 0


def check_modules() -> bool:
    """فحص استيراد وحدات البوت"""
    print("\n── 2) Module Imports ──")
    try:
        from config import RSS_SOURCES, CHANNEL_TAG, MARKET_COINS
        print(f"   ✅ config.py: {len(RSS_SOURCES)} مصدر RSS، tag={CHANNEL_TAG}، {len(MARKET_COINS)} عملة سوق")
        from sources import fetch_all_news, NewsItem
        print("   ✅ sources.py")
        from translator import google_translate
        print("   ✅ translator.py")
        from formatter import format_post, batch_header
        print("   ✅ formatter.py")
        from dedup import load_hashes, save_hashes
        print("   ✅ dedup.py")
        from quality import validate_post, score_news
        print("   ✅ quality.py")
        from images import resolve_photo, ASSETS_DIR
        cards = len(list(ASSETS_DIR.glob("*.jpg"))) if ASSETS_DIR.exists() else 0
        print(f"   ✅ images.py (صور بديلة: {cards}/5)")
        from bot import run_cycle
        print("   ✅ bot.py")
        return True
    except Exception as e:
        print(f"   ❌ فشل الاستيراد: {e}")
        return False


async def check_telegram(session: aiohttp.ClientSession) -> bool:
    """فحص الاتصال بـ Telegram API + صلاحية المشرف"""
    print("\n── 3) Telegram API ──")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("   ⚠️ تخطي (متغيرات مفقودة)")
        return False
    try:
        async with session.get(f"https://api.telegram.org/bot{token}/getMe",
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json(content_type=None)
            if data.get("ok"):
                bot = data["result"]
                print(f"   ✅ البوت: @{bot.get('username', '?')}")
            else:
                print(f"   ❌ getMe فشل: {data.get('description', '?')}")
                return False

        async with session.get(f"https://api.telegram.org/bot{token}/getChat",
                               params={"chat_id": chat_id},
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json(content_type=None)
            if data.get("ok"):
                chat = data["result"]
                print(f"   ✅ القناة: {chat.get('title', '?')} (type={chat.get('type', '?')})")
            else:
                print(f"   ❌ getChat فشل: {data.get('description', '?')}")
                return False

        async with session.get(
                f"https://api.telegram.org/bot{token}/getChatMember",
                params={"chat_id": chat_id, "user_id": bot["id"]},
                timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json(content_type=None)
            if data.get("ok"):
                status = data["result"].get("status", "?")
                print(f"   ✅ حالة البوت في القناة: {status}")
                if status != "administrator":
                    print("   ⚠️ البوت ليس أدمن — قد لا يستطيع النشر")
            else:
                print(f"   ⚠️ getChatMember: {data.get('description', '?')}")
        return True
    except Exception as e:
        print(f"   ❌ خطأ اتصال: {e}")
        return False


async def check_market(session: aiohttp.ClientSession) -> bool:
    """فحص مصادر أسعار السوق"""
    print("\n── 4) Market APIs ──")
    from sources import fetch_market_stats
    try:
        stats = await fetch_market_stats()
        if stats:
            btc = next((s for s in stats if s["symbol"] == "BTC"), stats[0])
            print(f"   ✅ الأسعار تعمل: {len(stats)} عملة (مثال: {btc['name']} ${btc['price']:,.0f})")
            return True
        print("   ⚠️ أسعار السوق غير متاحة الآن — الجولة ستعمل بدون ترويسة أسعار")
        return True  # ليست حرجة
    except Exception as e:
        print(f"   ⚠️ فحص الأسعار فشل (ليس حرجًا): {e}")
        return True


async def main() -> int:
    print("╔══════════════════════════════════════════════════╗")
    print("║        🔍 Bot Health Check — Pre-Run             ║")
    print("╚══════════════════════════════════════════════════╝")

    ok_env = check_env()
    ok_mod = check_modules()

    ok_tg = False
    async with aiohttp.ClientSession() as session:
        if ok_env:
            ok_tg = await check_telegram(session)
            await check_market(session)

    print("\n── Summary ──")
    print(f"   Env:      {'✅' if ok_env else '❌'}")
    print(f"   Modules:  {'✅' if ok_mod else '❌'}")
    print(f"   Telegram: {'✅' if ok_tg else '❌'}")

    if not (ok_env and ok_mod and ok_tg):
        print("\n⚠️ يوجد مشاكل — راجع الأخطاء أعلاه")
        return 1
    print("\n✅ كل شيء جاهز — يمكن تشغيل البوت")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
