# -*- coding: utf-8 -*-
"""
توليد TELEGRAM_SESSION — يُنفَّذ مرة واحدة فقط من جهازك المحلي.

الخطوات:
  1. حمّل api_id وapi_hash من https://my.telegram.org → API development tools
  2. نفّذ:  pip install telethon && python scripts/login.py
  3. أدخل رقم الهاتف (+9665xxxxxxxx) ورمز التحقق الذي يصلك في تيليجرام
  4. انسخ السلسلة الناتجة وضَعها في GitHub Secret باسم TELEGRAM_SESSION

⚠️ تحذير أمني: هذه السلسلة = وصول كامل لحسابك. لا تضعها في الكود ولا تشاركها.
   يُفضّل استخدام حساب تيليجرام مخصص لهذا الغرض.
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    print("=" * 60)
    print("  مولّد جلسة Telethon لبوت الأخبار")
    print("=" * 60)
    api_id = input("TELEGRAM_API_ID: ").strip()
    api_hash = input("TELEGRAM_API_HASH: ").strip()
    if not api_id.isdigit():
        raise SystemExit("api_id يجب أن يكون رقماً")

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.start()  # يطلب رقم الهاتف ورمز التحقق وكلمة مرور 2FA تفاعلياً

    session_string = client.session.save()
    me = await client.get_me()

    print("\n" + "=" * 60)
    print(f"تم الدخول باسم: {me.first_name} (@{me.username})")
    print("\nانسخ القيمة التالية إلى GitHub Secret باسم TELEGRAM_SESSION:\n")
    print(session_string)
    print("=" * 60)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
