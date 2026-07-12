#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكريبت تشخيص شامل - يفحص كل شيء دون إرسال لتلغرام
شغّله يدوياً من Actions → Diagnostics → Run workflow
"""

import os
import sys
import json
import hashlib
import feedparser
import requests
from datetime import datetime, timezone
from pathlib import Path

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")

SOURCES = {
    "CoinDesk":          "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph":     "https://cointelegraph.com/rss",
    "Bitcoinist":        "https://bitcoinist.com/feed/",
    "NewsBTC":           "https://www.newsbtc.com/feed/",
    "Decrypt":           "https://decrypt.co/feed",
    "CryptoSlate":       "https://cryptoslate.com/feed/",
    "Bitcoin News":      "https://news.bitcoin.com/feed/",
    "The Block":         "https://www.theblock.co/rss.xml",
    "Reuters Markets":   "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best",
    "Yahoo Finance":     "https://finance.yahoo.com/news/rssindex",
    "MarketWatch":       "https://www.marketwatch.com/feed/",
    "CNBC Top News":     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
}

CRYPTO_KW = {
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "blockchain", "altcoin", "stablecoin", "tether", "usdt", "usdc",
    "defi", "nft", "binance", "coinbase", "ripple", "xrp",
    "solana", "sol", "cardano", "ada", "dogecoin", "doge",
    "sec", "gensler", "etf", "spot etf", "blackrock", "fidelity",
    "grayscale", "halving", "mining",
    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة",
    "بلوكتشين", "بايننس", "كوين بيس",
}

OFFICIALS_KW = {
    "jerome powell", "powell", "janet yellen", "yellen", "gary gensler",
    "gensler", "christine lagarde", "lagarde", "biden", "trump",
    "federal reserve", "fed ", "fomc", "ecb", "imf",
    "interest rate", "rate cut", "rate hike",
    "باول", "جيلين", "لاجارد", "الفيدرالي", "الاحتياطي الفيدرالي",
    "الفائدة", "خفض الفائدة",
}

def line(c="=", n=70):
    print(c * n)

def step(n, t):
    print()
    line()
    print(f"  STEP {n}: {t}")
    line()

# ============================================================
# STEP 1: فحص المتغيرات
# ============================================================
step(1, "فحص المتغيرات السرية")
print(f"  TELEGRAM_TOKEN: {'✅ مضبوط (' + TELEGRAM_TOKEN[:8] + '...)' if TELEGRAM_TOKEN else '❌ غير مضبوط'}")
print(f"  CHAT_ID:        {'✅ مضبوط (' + str(CHAT_ID) + ')' if CHAT_ID else '❌ غير مضبوط'}")

# ============================================================
# STEP 2: فحص اتصال Telegram API
# ============================================================
step(2, "فحص Telegram API")
if not TELEGRAM_TOKEN:
    print("  ⏭️ تخطي (التوكن غير مضبوط)")
else:
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=15)
        if r.ok:
            info = r.json()["result"]
            print(f"  ✅ البوت: @{info.get('username')} (id: {info.get('id')})")
            print(f"  ✅ الاسم: {info.get('first_name')}")
        else:
            print(f"  ❌ فشل: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ خطأ: {e}")

# ============================================================
# STEP 3: فحص CHAT_ID
# ============================================================
step(3, "فحص CHAT_ID")
if not (TELEGRAM_TOKEN and CHAT_ID):
    print("  ⏭️ تخطي")
else:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getChat",
            params={"chat_id": CHAT_ID},
            timeout=15
        )
        if r.ok:
            chat = r.json()["result"]
            print(f"  ✅ النوع: {chat.get('type')}")
            print(f"  ✅ الاسم: {chat.get('title') or chat.get('first_name') or chat.get('username')}")
            if chat.get("type") in ("group", "supergroup", "channel"):
                # فحص صلاحية الإرسال
                try:
                    r2 = requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={
                            "chat_id": CHAT_ID,
                            "text": "🔧 رسالة اختبار من سكريبت التشخيص - يرجى الحذف",
                        },
                        timeout=15
                    )
                    if r2.ok:
                        print("  ✅ البوت يقدر يبعت لهذه القناة/المجموعة")
                        # احذف رسالة الاختبار
                        msg_id = r2.json()["result"]["message_id"]
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage",
                            json={"chat_id": CHAT_ID, "message_id": msg_id},
                            timeout=15
                        )
                        print("  🗑️ تم حذف رسالة الاختبار")
                    else:
                        print(f"  ❌ البوت ما يقدرش يبعت: {r2.status_code} - {r2.text[:200]}")
                        if "chat not found" in r2.text.lower():
                            print("     → CHAT_ID غلط")
                        elif "not enough rights" in r2.text.lower():
                            print("     → البوت ليس admin في القناة")
                        elif "bot was blocked" in r2.text.lower():
                            print("     → المستخدم حظر البوت")
                except Exception as e:
                    print(f"  ❌ خطأ في اختبار الإرسال: {e}")
        else:
            print(f"  ❌ فشل: {r.status_code} - {r.text[:200]}")
            if "chat not found" in r.text.lower():
                print("     → CHAT_ID غلط. للقناة استخدم @username أو -100xxxxxxxxx")
    except Exception as e:
        print(f"  ❌ خطأ: {e}")

# ============================================================
# STEP 4: فحص كل مصدر RSS
# ============================================================
step(4, "فحص مصادر RSS")
headers = {"User-Agent": "Mozilla/5.0 (NewsBot-Diag/1.0)"}
total_news = 0
sources_ok = 0
sources_fail = []

for name, url in SOURCES.items():
    try:
        feed = feedparser.parse(url, request_headers=headers)
        n = len(feed.entries)
        if n > 0:
            print(f"  ✅ {name:20s} → {n:3d} خبر")
            sources_ok += 1
            total_news += n
        else:
            print(f"  ⚠️  {name:20s} → 0 خبر (تحقق من الرابط)")
            sources_fail.append(name)
    except Exception as e:
        print(f"  ❌ {name:20s} → {e}")
        sources_fail.append(name)

print()
print(f"  📊 ملخص: {sources_ok}/{len(SOURCES)} مصدر يعمل، إجمالي {total_news} خبر")
if sources_fail:
    print(f"  ⚠️  مصادر فاشلة: {', '.join(sources_fail)}")

# ============================================================
# STEP 5: فحص الفلترة
# ============================================================
step(5, "فحص الفلترة (كم خبر مهم موجود الآن؟)")

if total_news == 0:
    print("  ⏭️ تخطي (لا أخبار متاحة)")
else:
    relevant = 0
    samples = []
    for name, url in SOURCES.items():
        try:
            feed = feedparser.parse(url, request_headers=headers)
            for entry in feed.entries:
                text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                crypto_m   = sum(1 for kw in CRYPTO_KW   if kw in text)
                official_m = sum(1 for kw in OFFICIALS_KW if kw in text)
                if crypto_m >= 2 or official_m >= 2:
                    relevant += 1
                    if len(samples) < 5:
                        samples.append({
                            "source": name,
                            "title": entry.get("title", "")[:80],
                            "crypto_matches": crypto_m,
                            "official_matches": official_m,
                        })
        except:
            pass

    print(f"  🎯 أخبار مهمة (score ≥ 2): {relevant} من أصل {total_news}")
    if samples:
        print()
        print("  📋 عينات من الأخبار المهمة المكتشفة:")
        for i, s in enumerate(samples, 1):
            print(f"     {i}. [{s['source']}] {s['title']}")
            print(f"        crypto={s['crypto_matches']} officials={s['official_matches']}")

# ============================================================
# STEP 6: فحص state.json
# ============================================================
step(6, "فحص state.json")
state_path = Path("state.json")
if state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        sent = len(state.get("sent_ids", []))
        last = state.get("last_run", "أبداً")
        print(f"  ✅ الملف موجود")
        print(f"  📊 أخبار مُرسلة سابقاً: {sent}")
        print(f"  📅 آخر تشغيل: {last}")
        if sent > 700:
            print(f"  ⚠️  الملف شبه ممتلئ ({sent}/{800})")
        if sent > 0 and last and "T" in last:
            print(f"  ℹ️  البوت اشتغل من قبل لكن ربما ما لقاش أخبار جديدة")
    except Exception as e:
        print(f"  ❌ خطأ: {e}")
else:
    print(f"  ℹ️  الملف غير موجود (سيُنشأ عند أول تشغيل ناجح)")

# ============================================================
# STEP 7: الخلاصة
# ============================================================
step(7, "الخلاصة والتوصيات")
print("""
  إذا لم تصلك أخبار على القناة، اتبع الترتيب التالي:

  1️⃣  لو STEP 2 فشل → TELEGRAM_TOKEN غلط
      → اذهب لـ @BotFather وتأكد من التوكن

  2️⃣  لو STEP 3 فشل → CHAT_ID غلط أو البوت ليس admin
      → للقناة: استخدم @username أو -100xxxxxxxxx
      → أضف البوت كـ Administrator في القناة

  3️⃣  لو STEP 4 فيه مصادر فاشلة → طبيعي، البعض يتوقف أحياناً
      → لكن لازم يكون في مصدر واحد على الأقل يعمل

  4️⃣  لو STEP 5 = 0 → ما فيش أخبار مهمة الآن (طبيعي)
      → انتظر أو خفف الفلتر (score < 1 بدل 2)

  5️⃣  لو STEP 6 ممتلئ → احذف state.json و commit
""")

print("=" * 70)
print(f"  انتهى التشخيص: {datetime.now(timezone.utc).isoformat()}")
print("=" * 70)
