#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار سريع - يبعت رسالة مباشرة للقناة للتأكد من الإعدادات
"""
import os
import requests
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")

print("=" * 50)
print("  اختبار الإرسال المباشر")
print("=" * 50)
print(f"  TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌'}")
print(f"  CHAT_ID: {CHAT_ID if CHAT_ID else '❌'}")
print()

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ المتغيرات ناقصة!")
    exit(1)

text = (
    f"🔧 <b>رسالة اختبار من GitHub Actions</b>\n\n"
    f"إذا وصلتك هذه الرسالة، فالبوت شغال والقناة مضبوطة.\n\n"
    f"🕐 التوقيت: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
)

r = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
    json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    },
    timeout=15
)

if r.ok:
    print("✅ تم الإرسال بنجاح! تحقق من قناتك على تلغرام")
    print(f"   message_id: {r.json()['result']['message_id']}")
else:
    print(f"❌ فشل الإرسال: {r.status_code}")
    print(f"   الرد: {r.text}")
    print()
    print("💡 الأسباب المحتملة:")
    if "chat not found" in r.text.lower():
        print("   - CHAT_ID غلط")
        print("   - للقناة استخدم: @your_channel أو -1001234567890")
        print("   - احصل على ID القناة: أضف البوت كأدمن ثم استخدم @getidsbot")
    elif "not enough rights" in r.text.lower():
        print("   - البوت ليس admin في القناة")
        print("   - من إعدادات القناة → Administrators → Add Bot")
    elif "bot was blocked" in r.text.lower():
        print("   - البوت محظور من المستخدم")
    elif "unauthorized" in r.text.lower():
        print("   - TELEGRAM_TOKEN غلط")
