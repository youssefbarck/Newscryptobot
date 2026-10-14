# -*- coding: utf-8 -*-
"""بناء الرسائل العربية الجذابة بصيغة HTML الجاهزة لتيليجرام"""
import html
import random
from datetime import datetime

from .analysis import human_usd
from .categories import CATEGORIES, COIN_AR, WHALE_DIRECTION_WHY
from .config import CHANNEL_SIGNATURE


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


# ------------------------------------------------------------ أدوات الوقت
def _day_part(hour: int) -> str:
    if 5 <= hour < 12:
        return "صباحًا"
    if 12 <= hour < 15:
        return "ظهرًا"
    if 15 <= hour < 18:
        return "عصرًا"
    return "مساءً"


def fmt_local_time(dt_local: datetime) -> str:
    return f"{dt_local.hour:02d}:{dt_local.minute:02d} {_day_part(dt_local.hour)}"


def rel_time_ar(pub_utc) -> str | None:
    """منذ ساعة • منذ 45 دقيقة • منذ 3 أيام"""
    if pub_utc is None:
        return None
    delta = datetime.now(pub_utc.tzinfo) - pub_utc
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "الآن"
    if mins < 60:
        return f"منذ {mins} دقيقة"
    hours = int(mins // 60)
    if hours == 1:
        return "منذ ساعة"
    if hours == 2:
        return "منذ ساعتين"
    if hours < 24:
        return f"منذ {hours} ساعات" if hours <= 10 else f"منذ {hours} ساعة"
    days = int(hours // 24)
    if days == 1:
        return "منذ يوم"
    if days == 2:
        return "منذ يومين"
    return f"منذ {days} أيام" if days <= 10 else f"منذ {days} يومًا"


# ------------------------------------------------------------ عناصر الجولة
BATCH_INTROS = [
    "🔥 <b>جولة أخبار الكريبتو</b> 🌍",
    "⚡ <b>ما فاتك في السوق الآن:</b>",
    "📡 <b>رصدولي… أخبار جديدة وصلت</b>",
    "🧨 <b>أقوى ما في المشهد:</b>",
]


def batch_header(count: int, now_local: datetime, market: list[dict] | None) -> str:
    lines = [random.choice(BATCH_INTROS)]
    count_txt = "أقوى خبر وصل الآن:" if count == 1 else f"أقوى {count} أخبار وصلت للتو:"
    lines.append(f"🕐 {fmt_local_time(now_local)} — {count_txt}")
    if market:
        lines.append("")
        lines.append("📊 <b>السوق الآن:</b>")
        for s in market:
            icon = "🟢" if s["change"] >= 0 else "🔴"
            sign = "+" if s["change"] >= 0 else ""
            if s["price"] >= 1000:
                price = f"{s['price']:,.0f}"
            elif s["price"] >= 1:
                price = f"{s['price']:,.2f}"
            else:
                price = f"{s['price']:.4f}".rstrip("0")
            lines.append(f'{icon} <b>{s["name"]}</b>: ${price} ({sign}{s["change"]:.1f}%)')
    return "\n".join(lines)


def test_message() -> str:
    return (
        "✅ <b>التهيئة تمت بنجاح!</b>\n\n"
        "🤖 بوت أخبار الكريبتو يعمل الآن…\n"
        "🐋 حركات الحيتان • 🚨 الاختراقات • 📈 التحركات الحادة\n"
        "⚖️ القوانين • 🚀 التقنية والشراكات\n\n"
        "⏰ ستصلك جولة جديدة كل ساعتين — الأخبار القوية فقط، بلا حشو وبلا ملل 😉"
    )


# ------------------------------------------------------------ خبر عادي
def news_message(item: dict, ar_title: str) -> str:
    cat = CATEGORIES[item["category"]]
    hook = random.choice(cat["hooks"])
    why = random.choice(cat["why"])
    facts = item.get("facts") or []

    lines = [
        f'{cat["emoji"]} <b>{cat["label"]}</b> — {hook}',
        "",
        f"<b>{esc(ar_title)}</b>",
        "",
        f"⚡ <b>باختصار:</b> {why}",
    ]
    if facts:
        lines.append("")
        lines.append("📌 <b>بالأرقام:</b>")
        lines.extend(facts)

    # سطر التذييل: الوقت + المصدر + توقيع القناة
    footer = []
    rel = rel_time_ar(item.get("published"))
    if rel:
        footer.append(f"⏱️ {rel}")
    if item.get("source"):
        footer.append(f'📡 {esc(item["source"])}')
    if footer:
        lines.append("")
        lines.append(" • ".join(footer))
    if CHANNEL_SIGNATURE:
        lines.append(esc(CHANNEL_SIGNATURE))

    msg = "\n".join(lines)
    # إن وُجدت صورة، التسمية محدودة بـ 1024 حرفًا — قصّر «باختصار» عند الحاجة
    if item.get("image") and len(msg) > 1000:
        why_short = why[: max(60, len(why) - (len(msg) - 1000) - 3)].rsplit(" ", 1)[0] + "…"
        msg = msg.replace(why, why_short)
    return msg


# ------------------------------------------------------------ خبر حيتان جاهز
def whale_message(item: dict) -> str:
    wd = item["whale_data"]
    cat = CATEGORIES["whale"]
    coin_ar = COIN_AR.get(wd["symbol"], wd["symbol"])

    if "بورصة" in wd["to_txt"]:
        direction = "to_exchange"
    elif "بورصة" in wd["from_txt"]:
        direction = "from_exchange"
    else:
        direction = "unknown"

    title = (
        f"حوت ينقل {wd['amount']:,.0f} {coin_ar} "
        f"(≈ {human_usd(wd['amount_usd'])}) من {wd['from_txt']} إلى {wd['to_txt']}"
    )
    hook = random.choice(cat["hooks"])
    why = WHALE_DIRECTION_WHY[direction]

    lines = [
        f'{cat["emoji"]} <b>{cat["label"]}</b> — {hook}',
        "",
        f"<b>{esc(title)}</b>",
        "",
        f"⚡ <b>باختصار:</b> {why}",
        "",
        "📌 <b>بالأرقام:</b>",
    ]
    lines.extend(item.get("facts") or [])

    footer = [f"⏱️ {rel_time_ar(item.get('published')) or 'الآن'}", "📡 Whale Alert"]
    lines.append("")
    lines.append(" • ".join(footer))
    if CHANNEL_SIGNATURE:
        lines.append(esc(CHANNEL_SIGNATURE))
    return "\n".join(lines)
