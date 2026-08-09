import os
import re
import json
import logging
import asyncio
import time
import urllib.request
from pathlib import Path
from threading import Thread

import feedparser
from deep_translator import GoogleTranslator
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application, CommandHandler,
    filters, ContextTypes,
)

# ═══════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
ADMIN_IDS = json.loads(os.environ.get("ADMIN_IDS", "[]"))
SEEN_FILE = Path("/tmp/seen_articles.json")
FETCH_INTERVAL = 900  # 15 minutes
MAX_ARTICLES = 5

SOURCES = [
    {"name": "CoinDesk", "url": "https://coindesk.com/arc/outboundfeeds/rss/", "priority": 1},
    {"name": "Watcher Guru", "url": "https://watcherguru.com/feed/", "priority": 2},
    {"name": "The Block", "url": "https://www.theblock.co/rss.xml", "priority": 3},
]

# ═══════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Flask (Render health check)
# ═══════════════════════════════════════════════════════════════
flask_app = Flask("")

@flask_app.route("/")
def health():
    return "OK", 200

# ═══════════════════════════════════════════════════════════════
# Self-ping (stay awake on Render free tier)
# ═══════════════════════════════════════════════════════════════
async def _self_ping():
    public_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not public_url:
        logger.warning("No RENDER_EXTERNAL_URL, self-ping disabled")
        return
    while True:
        await asyncio.sleep(300)
        try:
            urllib.request.urlopen(public_url, timeout=10)
            logger.info("Self-ping OK")
        except Exception as e:
            logger.warning(f"Self-ping failed: {e}")

# ═══════════════════════════════════════════════════════════════
# Seen articles (deduplication)
# ═══════════════════════════════════════════════════════════════
def load_seen():
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text())
        except Exception:
            pass
    return {"urls": {}, "titles": []}

def save_seen(data):
    try:
        SEEN_FILE.write_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass

def is_seen(url, title, seen):
    if url in seen["urls"]:
        return True
    return any(similar_titles(title, t) for t in seen["titles"])

def mark_seen(url, title, seen):
    seen["urls"][url] = time.time()
    seen["titles"].append(title)
    seen["titles"] = seen["titles"][-500:]
    cutoff = time.time() - 86400
    seen["urls"] = {k: v for k, v in seen["urls"].items() if v > cutoff}

def similar_titles(t1, t2, threshold=0.5):
    w1 = set(re.findall(r'\b\w{4,}\b', t1.lower()))
    w2 = set(re.findall(r'\b\w{4,}\b', t2.lower()))
    if not w1 or not w2:
        return False
    common = w1 & w2
    return len(common) / max(len(w1), len(w2)) > threshold

# ═══════════════════════════════════════════════════════════════
# RSS Fetcher
# ═══════════════════════════════════════════════════════════════
def fetch_rss(source):
    try:
        feed = feedparser.parse(source["url"])
        if feed.bozo and not feed.entries:
            logger.error(f"RSS parse error for {source['name']}: {feed.bozo_exception}")
            return []
        articles = []
        for entry in feed.entries[:20]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "") or entry.get("description", "")
            published = entry.get("published", "") or entry.get("updated", "")
            image = extract_image(entry, summary)
            if title and link:
                articles.append({
                    "title": title,
                    "link": link,
                    "summary": clean_html(summary),
                    "image": image,
                    "source": source["name"],
                    "priority": source["priority"],
                    "published": published,
                })
        return articles
    except Exception as e:
        logger.error(f"RSS fetch error for {source['name']}: {e}")
        return []

def extract_image(entry, summary_html=""):
    # 1. media:content
    if "media_content" in entry:
        for media in entry["media_content"]:
            if "url" in media:
                return media["url"]
    # 2. media:thumbnail
    if "media_thumbnail" in entry:
        for thumb in entry["media_thumbnail"]:
            if "url" in thumb:
                return thumb["url"]
    # 3. enclosure with image type
    if "enclosures" in entry:
        for enc in entry["enclosures"]:
            if enc.get("type", "").startswith("image"):
                return enc.get("href", "") or enc.get("url", "")
    # 4. links with image type
    if "links" in entry:
        for link in entry["links"]:
            if link.get("type", "").startswith("image"):
                return link.get("href", "")
    # 5. img in summary HTML
    if summary_html:
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)', summary_html)
        if img_match:
            return img_match.group(1)
    return ""

def clean_html(text):
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ═══════════════════════════════════════════════════════════════
# OG Image fallback
# ═══════════════════════════════════════════════════════════════
def fetch_og_image(url):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read(8000).decode("utf-8", errors="replace")
            match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
            if match:
                return match.group(1)
            match2 = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
            if match2:
                return match2.group(1)
    except Exception:
        pass
    return ""

# ═══════════════════════════════════════════════════════════════
# Translator
# ═══════════════════════════════════════════════════════════════
def translate_text(text):
    if not text or len(text.strip()) < 10:
        return ""
    try:
        translator = GoogleTranslator(source='auto', target='ar')
        result = translator.translate(text[:3000])
        if result:
            return result.strip()
    except Exception as e:
        logger.error(f"Translation error: {e}")
    return ""

def is_translation_good(original, translated):
    if not translated:
        return False
    if not re.search(r'[\u0600-\u06FF]', translated):
        return False
    if len(translated) < len(original) * 0.15:
        return False
    if translated.strip().lower() == original.strip().lower():
        return False
    return True

# ═══════════════════════════════════════════════════════════════
# Format article
# ═══════════════════════════════════════════════════════════════
def format_article(article):
    lines = []
    lines.append(f"\U0001F4F0 *{article['source']}*")
    lines.append("")
    lines.append(article["title_ar"])
    if article.get("summary_ar"):
        lines.append("")
        lines.append(article["summary_ar"][:500])
    lines.append("")
    lines.append(f"\U0001F517 [المصدر]({article['link']})")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
# Fetch & Post
# ═══════════════════════════════════════════════════════════════
async def fetch_and_post(bot):
    if not CHANNEL_ID:
        logger.error("CHANNEL_ID not set!")
        return

    seen = load_seen()
    all_articles = []

    for source in SOURCES:
        articles = fetch_rss(source)
        all_articles.extend(articles)
        logger.info(f"Fetched {len(articles)} from {source['name']}")

    # Sort by published date (newest first)
    all_articles.sort(key=lambda a: a.get("published", ""), reverse=True)

    posted = 0
    for article in all_articles:
        if posted >= MAX_ARTICLES:
            break

        # Dedup
        if is_seen(article["link"], article["title"], seen):
            continue

        # Image required
        if not article["image"]:
            article["image"] = fetch_og_image(article["link"])
        if not article["image"]:
            logger.info(f"Skip (no image): {article['title'][:60]}")
            continue

        # Translate title
        title_ar = translate_text(article["title"])
        if not is_translation_good(article["title"], title_ar):
            logger.info(f"Skip (bad translation): {article['title'][:60]}")
            continue

        # Translate summary
        summary_ar = ""
        if article["summary"] and len(article["summary"]) > 30:
            summary_ar = translate_text(article["summary"][:1000])
            if not is_translation_good(article["summary"], summary_ar):
                summary_ar = ""

        article["title_ar"] = title_ar
        article["summary_ar"] = summary_ar

        caption = format_article(article)

        try:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=article["image"],
                caption=caption,
                parse_mode="Markdown",
                read_timeout=30,
                write_timeout=30,
            )
            posted += 1
            mark_seen(article["link"], article["title"], seen)
            logger.info(f"Posted: {article['title'][:60]}")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Post error: {e}")

    save_seen(seen)
    logger.info(f"Cycle done. Posted {posted} articles.")

# ═══════════════════════════════════════════════════════════════
# News loop
# ═══════════════════════════════════════════════════════════════
async def news_loop(application):
    bot = application.bot
    while True:
        try:
            await fetch_and_post(bot)
        except Exception as e:
            logger.error(f"News loop error: {e}", exc_info=True)
        await asyncio.sleep(FETCH_INTERVAL)

# ═══════════════════════════════════════════════════════════════
# Admin commands
# ═══════════════════════════════════════════════════════════════
async def start_cmd(update, context):
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "\U0001F4E1 *بوت أخبار الكريبتو*\n\n"
        "المصادر: CoinDesk, Watcher Guru, The Block\n"
        f"القناة: `{CHANNEL_ID}`\n"
        f"التحديث: كل {FETCH_INTERVAL // 60} دقيقة\n\n"
        "الأوامر:\n"
        "/fetch — جلب يدوي\n"
        "/stats — الإحصائيات\n"
        "/clear — مسح الذاكرة",
        parse_mode="Markdown",
    )

async def fetch_cmd(update, context):
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("\u23F3 جاري جلب الأخبار...")
    await fetch_and_post(context.bot)
    await update.message.reply_text("\u2705 تم!")

async def stats_cmd(update, context):
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        return
    seen = load_seen()
    total = len(seen["urls"])
    sources_ok = 0
    for src in SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            if feed.entries:
                sources_ok += 1
        except Exception:
            pass
    await update.message.reply_text(
        f"\U0001F4CA *الإحصائيات*\n\n"
        f"الأخبار المرسلة: *{total}*\n"
        f"المصادر النشطة: {sources_ok}/{len(SOURCES)}\n"
        f"فاصل التحديث: {FETCH_INTERVAL // 60} دقيقة",
        parse_mode="Markdown",
    )

async def clear_cmd(update, context):
    user = update.effective_user
    if ADMIN_IDS and user.id not in ADMIN_IDS:
        return
    SEEN_FILE.unlink(missing_ok=True)
    await update.message.reply_text("\U0001F5D1 تم مسح ذاكرة الأخبار.")

# ═══════════════════════════════════════════════════════════════
# Startup
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    def _run_flask():
        flask_app.run(host="0.0.0.0", port=port, use_reloader=False)
    Thread(target=_run_flask, daemon=True).start()
    print(f"[OK] Flask on port {port}", flush=True)

    print("[OK] Building bot...", flush=True)
    app = Application.builder().token(BOT_TOKEN).build()

    async def post_init(application):
        asyncio.create_task(_self_ping())
        asyncio.create_task(news_loop(application))
        print("[OK] Self-ping + News loop started", flush=True)
        try:
            await application.bot.send_message(
                chat_id=CHANNEL_ID,
                text="\U0001F680 *بوت الأخبار بدأ العمل*\nالمصادر: CoinDesk, Watcher Guru, The Block\nتحديث كل 15 دقيقة",
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"[WARN] Startup message failed: {e}", flush=True)

    app.post_init = post_init
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("fetch", fetch_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    print("[OK] Starting polling...", flush=True)
    app.run_polling(drop_pending_updates=True)
