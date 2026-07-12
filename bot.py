#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
News Bot - يرسل الأخبار المهمة فقط إلى تلغرام
يعمل على GitHub Actions كل 5 دقائق
"""

import os
import sys
import json
import time
import hashlib
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
MAX_HISTORY   = 500        # احتفظ بآخر 500 خبر مُرسل
SEND_DELAY    = 1.5        # ثانية بين كل رسالة (لتجنب flood limit)
HTTP_TIMEOUT  = 30         # مهلة الطلب

# مصادر RSS - عدّلها حسب احتياجك
SOURCES = {
    "BBC عربي":    "https://feeds.bbci.co.uk/arabic/rss.xml",
    "العربي":      "https://www.alaraby.co.uk/rss",
    "RT عربي":     "https://arabic.rt.com/rss/",
    "سكاي نيوز":   "https://www.skynewsarabia.com/web/rss/rss.xml",
    "الحرة":       "https://www.alhurra.com/rss feeds/arabic.xml",
    "الجزيرة":     "https://www.aljazeera.net/aljazeerarss/a7c186be-5f6d-4d60-8a26-7c1cd6c0e922/49e749e7-4d4f-4b3f-8a4e-4b6c0e9f4d4d",
    # مصادر جزائرية (قد تتغير الروابط - راجعها دورياً)
    # "الشروق":    "https://www.echoroukonline.com/feed",
    # "الخبر":     "https://www.elkhabar.com/feed",
    # "النهار":    "https://www.ennaharonline.com/feed",
}

# كلمات تدل على أهمية الخبر (تستخدم للفلترة)
IMPORTANT_KEYWORDS = {
    # عربي
    "عاجل", "مهم", "خطير", "حصري", "كسر", "انفجار", "اغتيال",
    "هجوم", "حرب", "إعلان", "قرار", "قمة", "اتفاق", "وفاة",
    "استقالة", "انتخابات", "إنذار", "تحذير", "طارئ", "فلاش",
    "تصعيد", "هدنة", "وقف إطلاق", "زلزال", "حرائق", "كارثة",
    "زلزال", "إعصار", "فيضان", "حريق", "اغتيال", "محاولة",
    # إنجليزي
    "breaking", "urgent", "exclusive", "major", "critical",
    "alert", "emergency", "crisis",
}

# ============================================================
# دوال إدارة الحالة (state.json)
# ============================================================

def load_state():
    """تحميل حالة البوت (الأخبار المُرسلة)"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ خطأ في قراءة state.json: {e}")
    return {"sent_ids": [], "last_run": None, "total_sent": 0}

def save_state(state):
    """حفظ الحالة بعد التشغيل"""
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ============================================================
# دوال الأخبار
# ============================================================

def get_news_id(entry):
    """توليد ID فريد للخبر باستخدام العنوان (يمنع التكرار بين المصادر)"""
    title = entry.get("title", "").strip().lower()
    if title:
        return hashlib.md5(title.encode()).hexdigest()[:16]
    return entry.get("id") or entry.get("link") or "unknown"

def is_important(entry):
    """فحص إن كان الخبر مهماً بناءً على الكلمات المفتاحية"""
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()

    for kw in IMPORTANT_KEYWORDS:
        if kw in text:
            return True, kw

    # وسوم RSS (بعض المصادر تستخدمها)
    for tag in entry.get("tags", []):
        term = tag.get("term", "").lower()
        if term in {"breaking", "urgent", "flash", "عاجل", "مهم"}:
            return True, term

    return False, None

def fetch_news():
    """جمع الأخبار من كل المصادر"""
    all_news = []
    headers = {"User-Agent": "Mozilla/5.0 (NewsBot/1.0)"}

    for name, url in SOURCES.items():
        try:
            feed = feedparser.parse(url, request_headers=headers)
            if feed.bozo and not feed.entries:
                print(f"⚠️ {name}: فشل تحميل Feed")
                continue
            for entry in feed.entries:
                entry["_source"] = name
                all_news.append(entry)
            print(f"✅ {name}: {len(feed.entries)} خبر")
        except Exception as e:
            print(f"❌ {name}: {e}")

    return all_news

# ============================================================
# دالة الإرسال إلى تلغرام
# ============================================================

def send_to_telegram(text):
    """إرسال رسالة إلى تلغرام"""
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
    print("=" * 50)
    print(f"⏰ تشغيل البوت: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 50)

    # التحقق من المتغيرات
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ المتغيرات السرية غير مضبوطة!")
        sys.exit(1)

    # تحميل الحالة
    state = load_state()
    sent_ids = set(state["sent_ids"])
    print(f"📊 أخبار مُرسلة سابقاً: {len(sent_ids)}")

    # جمع الأخبار
    all_news = fetch_news()
    print(f"📰 إجمالي الأخبار المتاحة: {len(all_news)}")

    if not all_news:
        print("⚠️ لا أخبار جديدة. إعادة المحاولة بعد 5 دقائق.")
        save_state(state)
        return

    # فلترة الأخبار المهمة والجديدة
    important_new = []
    for entry in all_news:
        nid = get_news_id(entry)
        if nid in sent_ids:
            continue
        is_imp, reason = is_important(entry)
        if is_imp:
            important_new.append((entry, reason, nid))

    print(f"🚨 أخبار مهمة جديدة: {len(important_new)}")

    if not important_new:
        print("✅ لا أخبار مهمة جديدة. ننتظر 5 دقائق...")
        save_state(state)
        return

    # إرسال الأخبار
    sent_count = 0
    for entry, reason, nid in important_new:
        source = entry["_source"]
        title  = entry.get("title", "").strip()
        link   = entry.get("link", "")
        pub    = entry.get("published", "")[:25]

        text = (
            f"🚨 <b>خبر عاجل</b>\n\n"
            f"<b>{title}</b>\n\n"
            f"📡 المصدر: {source}\n"
            f"🏷 السبب: {reason}\n"
            f"🕐 النشر: {pub}\n\n"
            f"🔗 {link}"
        )

        if send_to_telegram(text):
            sent_count += 1
            sent_ids.add(nid)
            print(f"  ✉️ تم إرسال: {title[:50]}...")
            time.sleep(SEND_DELAY)
        else:
            print(f"  ❌ فشل إرسال: {title[:50]}...")

    # حفظ الحالة
    state["sent_ids"] = list(sent_ids)[-MAX_HISTORY:]
    state["total_sent"] = state.get("total_sent", 0) + sent_count
    save_state(state)

    print("=" * 50)
    print(f"📤 تم إرسال {sent_count} خبر")
    print(f"📊 الإجمالي التراكمي: {state['total_sent']}")
    print("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ خطأ غير متوقع: {e}")
        sys.exit(1)
