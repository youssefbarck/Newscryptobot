#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto & Macro News Bot
-----------------------
بوت يرسل الأخبار المهمة فقط إلى تلغرام:
  1) أخبار الكريبتو (Bitcoin, Ethereum, ETFs, SEC, exchanges, ...)
  2) تصريحات المسؤولين والرؤساء المؤثرة على الأسواق المالية
     (Fed, ECB, Treasury, Central Banks, Presidents, Ministers, ...)

يعمل على GitHub Actions كل 5 دقائق.
"""

import os
import sys
import json
import time
import hashlib
import re
import feedparser
import requests
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# الإعدادات
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")

STATE_FILE    = Path("state.json")
MAX_HISTORY   = 800       # احتفظ بآخر 800 خبر مُرسل
SEND_DELAY    = 1.5       # ثانية بين كل رسالة
HTTP_TIMEOUT  = 30

# ============================================================
# مصادر RSS - كريبتو + ماكرو مالي
# ============================================================

SOURCES = {
    # ---- كريبتو (إنجليزي) ----
    "CoinDesk":          "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph":     "https://cointelegraph.com/rss",
    "Bitcoinist":        "https://bitcoinist.com/feed/",
    "NewsBTC":           "https://www.newsbtc.com/feed/",
    "Decrypt":           "https://decrypt.co/feed",
    "CryptoSlate":       "https://cryptoslate.com/feed/",
    "Bitcoin News":      "https://news.bitcoin.com/feed/",
    "The Block":         "https://www.theblock.co/rss.xml",

    # ---- ماكرو / أسواق / مسؤولون ----
    "Reuters Markets":   "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best",
    "Yahoo Finance":     "https://finance.yahoo.com/news/rssindex",
    "MarketWatch":       "https://www.marketwatch.com/feed/",
    "CNBC Top News":     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",

    # ---- كريبتو (عربي) ----
    "CoinArabia":        "https://www.coinarabia.com/feed/",
    # أضف المزيد إن وُجد
}

# ============================================================
# كلمات التصنيف
# ============================================================

# (1) كلمات الكريبتو - إنجليزي
CRYPTO_KEYWORDS_EN = {
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "blockchain", "altcoin", "stablecoin", "tether", "usdt", "usdc",
    "defi", "nft", "binance", "coinbase", "kraken", "ripple", "xrp",
    "solana", "sol", "cardano", "ada", "dogecoin", "doge", "shiba",
    "sec", "gensler", "etf", "spot etf", "blackrock", "fidelity",
    "grayscale", "halving", "mining", "hashrate", "stablecoin",
    "token", "airdrop", "exchange", "wallet", "custody", "staking",
    "web3", "metaverse", "layer 2", "l2", "rollup", "bridge",
    "ico", "ido", "presale", "futures", "options", "leverage",
    "liquidation", "funding rate", "open interest",
}

# (2) كلمات الكريبتو - عربي
CRYPTO_KEYWORDS_AR = {
    "بيتكوين", "إيثيريوم", "إيثر", "عملة رقمية", "عملات رقمية",
    "كريبتو", "تشفيرية", "عملة مشفرة", "عملات مشفرة",
    "بلوكتشين", "سلسلة الكتل", "ألتكوين", "ستايبل كوين",
    "ديفاي", "إن إف تي", "بايننس", "كوين بيس", "ريبل",
    "سولانا", "كاردانو", "دوجكوين", "تذر", "يوس دي سي",
    "تهافت", "هاينغ", "تعدين", "محفظة", "تبادل",
    "صندوق تداول", "إيتف", "بلاك روك", "غراي سكيل",
    "توكين", "إيردروب", "بورصة", "منصة تداول",
}

# (3) مسؤولون ومؤسسات - إنجليزي
OFFICIALS_KEYWORDS_EN = {
    # أشخاص
    "jerome powell", "powell", "janet yellen", "yellen", "gary gensler",
    "gensler", "christine lagarde", "lagarde", "biden", "trump",
    "harris", "warren", "xi jinping", "jinping", "macron",
    "scholz", "sunak", "kishida", "modi", "erdogan",
    "mbs", "bin salman", "el-erian", "dimon", "buffett",

    # مؤسسات
    "federal reserve", "fed ", "fomc", "ecb", "bank of england",
    "boe", "bank of japan", "boj", "pboc", "imf", "world bank",
    "treasury", "u.s. treasury", "sec ", "cftc", "occ",
    "central bank", "central banks", "basel", "fsb",

    # قرارات وأحداث
    "interest rate", "rate cut", "rate hike", "fed cuts", "fed hikes",
    "monetary policy", "fomc minutes", "fed minutes", "rate decision",
    "press conference", "speech by", "testimony", "congress",
    "summit", "g7", "g20", "wef", "davos", "jackson hole",
    "executive order", "regulation", "regulator", "ban", "sanction",
    "tariff", "trade war", "qa", "question and answer",
}

# (4) مسؤولون ومؤسسات - عربي
OFFICIALS_KEYWORDS_AR = {
    # أشخاص
    "باول", "جيروم باول", "جيلين", "جانيت يلين", "غانسلر",
    "لاجارد", "كريستين لاجارد", "بايدن", "ترامب", "هاريس",
    "شي جين بينغ", "جين بينغ", "ماكرون", "شولتز", "سوناك",
    "كيشيدا", "مودي", "أردوغان", "محمد بن سلمان", "ابن سلمان",
    "العداني", "دايمون", "بافيت",

    # مؤسسات
    "الاحتياطي الفيدرالي", "الفيدرالي", "البنك المركزي الأوروبي",
    "بنك إنجلترا", "بنك اليابان", "صندوق النقد الدولي",
    "البنك الدولي", "وزارة الخزانة", "الخزانة الأمريكية",
    "هيئة الأوراق المالية", "البنك المركزي",

    # قرارات وأحداث
    "أسعار الفائدة", "خفض الفائدة", "رفع الفائدة", "قرار الفائدة",
    "السياسة النقدية", "محضر الاجتماع", "مؤتمر صحفي",
    "قمة", "مجموعة السبع", "مجموعة العشرين", "منتدى دافوس",
    "قرار رئاسي", "تنظيم", "جهة رقابية", "حظر", "عقوبات",
    "تعريفات", "حرب تجارية",
}

# (5) أسواق مالية - إنجليزي (تُستعمل مع تصريحات المسؤولين)
MARKET_KEYWORDS_EN = {
    "stock market", "wall street", "s&p", "nasdaq", "dow jones",
    "equity", "equities", "bond", "bonds", "treasury yields",
    "yields", "dollar index", "dxy", "oil prices", "gold prices",
    "risk assets", "risk-off", "risk-on", "rally", "selloff",
    "bear market", "bull market", "correction", "crash", "surge",
    "plunge", "volatility", "vix", "futures", "recession",
    "inflation", "cpi", "ppi", "jobs report", "nonfarm",
    "gdp", "pmi", "consumer sentiment",
}

# (6) أسواق مالية - عربي
MARKET_KEYWORDS_AR = {
    "سوق الأسهم", "أسواق المال", "وول ستريت", "ناسداك", "داو جونز",
    "سندات", "عوائد السندات", "مؤشر الدولار", "أسعار النفط",
    "أسعار الذهب", "مخاطرة", "تهريب من المخاطر", "اقتحام المخاطر",
    "صعود", "هبوط", "سوق هابطة", "سوق صاعدة", "تصحيح",
    "انهيار", "ارتفاع حاد", "تقلب", "تقلبات", "ركود",
    "تضخم", "ناتج محلي", "تقرير الوظائف",
}

# (7) كلمات ترفع درجة الأهمية (أي مصطلح عاجل)
URGENT_KEYWORDS = {
    "breaking", "urgent", "exclusive", "flash", "just in",
    "عاجل", "مهم", "خطير", "حصري", "فلاش", "طاريء",
}

# ============================================================
# دوال مساعدة
# ============================================================

def normalize_text(text):
    """توحيد النص لسهولة المطابقة"""
    if not text:
        return ""
    text = text.lower()
    # توحيد الألف
    text = re.sub(r"[إأآا]", "ا", text)
    # توحيد الياء
    text = text.replace("ى", "ي")
    # توحيد الهمزة
    text = text.replace("ؤ", "و").replace("ئ", "ي")
    # إزالة التشكيل
    text = re.sub(r"[\u064B-\u0652]", "", text)
    return text

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ خطأ في قراءة state.json: {e}")
    return {"sent_ids": [], "last_run": None, "total_sent": 0}

def save_state(state):
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_news_id(entry):
    """ID فريد للخبر (md5 على العنوان)"""
    title = entry.get("title", "").strip().lower()
    if title:
        return hashlib.md5(title.encode()).hexdigest()[:16]
    return entry.get("id") or entry.get("link") or "unknown"

# ============================================================
# تصنيف الخبر
# ============================================================

def classify_news(entry):
    """
    يرجع: (category, reason, score)
    category ∈ {"crypto", "official", "market", None}
    score = عدد الكلمات المطابقة
    """
    title    = entry.get("title", "")
    summary  = entry.get("summary", "")
    text_norm = normalize_text(title + " " + summary)

    if not text_norm:
        return None, None, 0

    # عدّ المطابقات في كل فئة
    crypto_matches   = sum(1 for kw in CRYPTO_KEYWORDS_EN   if kw in text_norm) \
                     + sum(1 for kw in CRYPTO_KEYWORDS_AR   if normalize_text(kw) in text_norm)
    official_matches = sum(1 for kw in OFFICIALS_KEYWORDS_EN if kw in text_norm) \
                     + sum(1 for kw in OFFICIALS_KEYWORDS_AR if normalize_text(kw) in text_norm)
    market_matches   = sum(1 for kw in MARKET_KEYWORDS_EN   if kw in text_norm) \
                     + sum(1 for kw in MARKET_KEYWORDS_AR   if normalize_text(kw) in text_norm)

    urgent_match = any(kw in text_norm for kw in URGENT_KEYWORDS)

    # اختيار الفئة ذات أعلى مطابقة
    scores = {
        "crypto":   crypto_matches,
        "official": official_matches,
        "market":   market_matches,
    }
    best_cat = max(scores, key=scores.get)
    best_score = scores[best_cat]

    # شرط القبول: تطابق واحد على الأقل، أو كلمة عاجلة + تطابق في فئة أخرى
    if best_score == 0:
        if urgent_match:
            return "market", "عاجل", 1  # خبر عاجل بدون فئة واضحة -> نعتبره سوق
        return None, None, 0

    reason = ""
    if urgent_match:
        reason = "عاجل + " + best_cat
    else:
        reason = best_cat

    return best_cat, reason, best_score + (1 if urgent_match else 0)

# ============================================================
# جمع الأخبار
# ============================================================

def fetch_news():
    all_news = []
    headers = {"User-Agent": "Mozilla/5.0 (NewsBot/1.0)"}

    for name, url in SOURCES.items():
        try:
            feed = feedparser.parse(url, request_headers=headers)
            if feed.bozo and not feed.entries:
                print(f"⚠️  {name}: فشل تحميل Feed")
                continue
            for entry in feed.entries:
                entry["_source"] = name
                all_news.append(entry)
            print(f"✅ {name}: {len(feed.entries)} خبر")
        except Exception as e:
            print(f"❌ {name}: {e}")

    return all_news

# ============================================================
# الإرسال إلى تلغرام
# ============================================================

CAT_EMOJI = {
    "crypto":   "₿",
    "official": "🏛",
    "market":   "📈",
}

CAT_LABEL_AR = {
    "crypto":   "كريبتو",
    "official": "تصريح مسؤول",
    "market":   "أسواق مالية",
}

def send_to_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ TELEGRAM_TOKEN أو CHAT_ID غير مضبوط")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        if resp.ok:
            return True
        print(f"❌ Telegram API: {resp.status_code} - {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        print(f"❌ خطأ شبكة: {e}")
        return False

# ============================================================
# البرنامج الرئيسي
# ============================================================

def main():
    print("=" * 60)
    print(f"⏰ تشغيل البوت: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ المتغيرات السرية غير مضبوطة!")
        sys.exit(1)

    state = load_state()
    sent_ids = set(state["sent_ids"])
    print(f"📊 أخبار مُرسلة سابقاً: {len(sent_ids)}")

    all_news = fetch_news()
    print(f"📰 إجمالي الأخبار المتاحة: {len(all_news)}")

    if not all_news:
        print("⚠️ لا أخبار. إعادة المحاولة بعد 5 دقائق.")
        save_state(state)
        return

    # فلترة وتصنيف
    relevant_news = []
    for entry in all_news:
        nid = get_news_id(entry)
        if nid in sent_ids:
            continue

        category, reason, score = classify_news(entry)
        if category is None:
            continue

        # شرط الأهمية:
        # - score >= 2 للفئات (يقلل الضجيج)
        # - أو كلمة عاجلة + score >= 1
        # - أو خبر يحتوي كلمة عاجلة فقط (قد يكون مهماً)
        if score < 2 and "عاجل" not in (reason or ""):
            continue
        if "عاجل" in (reason or "") and score < 1:
            continue

        relevant_news.append((entry, category, reason, nid, score))

    # ترتيب: الأعلى تطابقاً أولاً
    relevant_news.sort(key=lambda x: x[4], reverse=True)

    print(f"🎯 أخبار كريبتو/تصريحات/أسواق: {len(relevant_news)}")

    if not relevant_news:
        print("✅ لا أخبار مهمة جديدة. ننتظر 5 دقائق...")
        save_state(state)
        return

    sent_count = 0
    for entry, category, reason, nid, score in relevant_news:
        source = entry["_source"]
        title  = entry.get("title", "").strip()
        link   = entry.get("link", "")
        pub    = entry.get("published", "")[:25]
        emoji  = CAT_EMOJI.get(category, "📰")
        label  = CAT_LABEL_AR.get(category, category)

        text = (
            f"{emoji} <b>{label}</b>  "
            f"<i>[{source}]</i>\n\n"
            f"<b>{title}</b>\n\n"
            f"🏷 السبب: {reason}\n"
            f"🕐 النشر: {pub}\n\n"
            f"🔗 {link}"
        )

        if send_to_telegram(text):
            sent_count += 1
            sent_ids.add(nid)
            print(f"  ✉️  [{category}] {title[:60]}...")
            time.sleep(SEND_DELAY)
        else:
            print(f"  ❌ فشل إرسال: {title[:60]}...")

    state["sent_ids"] = list(sent_ids)[-MAX_HISTORY:]
    state["total_sent"] = state.get("total_sent", 0) + sent_count
    save_state(state)

    print("=" * 60)
    print(f"📤 تم إرسال {sent_count} خبر")
    print(f"📊 الإجمالي التراكمي: {state['total_sent']}")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"❌ خطأ غير متوقع: {e}")
        traceback.print_exc()
        sys.exit(1)
