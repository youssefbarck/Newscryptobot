# -*- coding: utf-8 -*-
"""📝 بناء المنشورات العربية الجذابة بصيغة HTML الجاهزة لتيليجرام."""
import html
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from categories import CATEGORIES, COIN_AR, WHALE_DIRECTION_WHY
from config import CHANNEL_TAG, DISPLAY_TZ
from quality import human_usd

BATCH_INTROS = [
    "🔥 <b>جولة أخبار الكريبتو</b> 🌍",
    "⚡ <b>ما فاتك في السوق الآن:</b>",
    "📡 <b>رصدولي… أخبار جديدة وصلت</b>",
    "🧨 <b>أقوى ما في المشهد:</b>",
]


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


def rel_time_ar(ts: float) -> str | None:
    """منذ ساعة • منذ 45 دقيقة • منذ 3 أيام (ts بالثواني أو 0 لغير معروف)."""
    if not ts:
        return None
    delta = datetime.now(ZoneInfo("UTC")).timestamp() - ts
    mins = int(delta // 60)
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


# ------------------------------------------------------------ عناوين الجولة
def _price_str(price: float) -> str:
    """تنسيق السعر: 81,400 / 727.28 / 0.0817 / 0.0000112."""
    if price >= 1000:
        return f"{price:,.0f}"
    if price >= 1:
        return f"{price:,.2f}"
    if price >= 0.01:
        return f"{price:.4f}".rstrip("0")
    return f"{price:.8f}".rstrip("0")  # أسعار صغيرة جدًا (بيبي ومثيلاته)


def _mover_lines(movers: dict | None) -> list[str]:
    """سطرا «الأكثر صعودًا/نزولًا اليوم» — لترويسة الفترة المسائية."""
    if not movers:
        return []
    lines = []
    for m in movers.get("gainers") or []:
        change = m["change"]
        lines.append(f"🚀 <b>الأكثر صعودًا اليوم:</b> {esc(str(m['name']))} — "
                     f"${_price_str(m['price'])} (+{change:.1f}%)")
    for m in movers.get("losers") or []:
        lines.append(f"🔻 <b>الأكثر نزولًا اليوم:</b> {esc(str(m['name']))} — "
                     f"${_price_str(m['price'])} ({m['change']:.1f}%)")
    return lines


def batch_header(count: int, now_local: datetime, market: list[dict] | None,
                 movers: dict | None = None) -> str:
    lines = [_pick(BATCH_INTROS, "batch_intro")]
    count_txt = "أقوى خبر وصل الآن:" if count == 1 else f"أقوى {count} أخبار وصلت للتو:"
    lines.append(f"🕐 {fmt_local_time(now_local)} — {count_txt}")

    # الفترة المسائية: بيتكوين وإيثريوم فقط + الأكثر صعودًا ونزولًا اليوم،
    # وبقية الفترات: القائمة الثابتة المعتادة (وينطبق أيضًا لو فشل جلب المتحركين)
    evening = _day_part(now_local.hour) == "مساءً"
    mover_lines = _mover_lines(movers) if (evening and movers) else []

    if market or mover_lines:
        lines.append("")
        lines.append("📊 <b>السوق الآن:</b>")
        shown = market
        if mover_lines and market:
            shown = [s for s in market if s.get("symbol") in ("BTC", "ETH")] or market[:2]
        for s in (shown or []):
            icon = "🟢" if s["change"] >= 0 else "🔴"
            sign = "+" if s["change"] >= 0 else ""
            lines.append(f'{icon} <b>{s["name"]}</b>: ${_price_str(s["price"])} ({sign}{s["change"]:.1f}%)')
        lines.extend(mover_lines)
    return "\n".join(lines)


def test_message() -> str:
    return (
        "✅ <b>التهيئة تمت بنجاح!</b>\n\n"
        f"🤖 بوت أخبار الكريبتو يعمل الآن… {CHANNEL_TAG}\n"
        "🐋 حركات الحيتان • 🚨 الاختراقات • 📈 التحركات الحادة\n"
        "⚖️ القوانين • 🚀 التقنية والشراكات\n\n"
        "⏰ ستصلك جولة جديدة كل ساعتين — الأخبار القوية فقط، بلا حشو وبلا ملل 😉"
    )


def doctor_message() -> str:
    return ("🩺 <b>فحص تشخيصي:</b> البوت قادر على النشر في هذه المحادثة ✅")


# ذاكرة آخر جملة سُحبت لكل مفتاح — تمنع تكرار نفس القالب في منشورين متتاليين
_LAST_PICK: dict[str, str] = {}


def _pick(options: list[str], key: str = "") -> str:
    """اختيار عشوائي لجملة تلقائية — بلا علامات استفهام وبلا تكرار متتالٍ.

    فحص سلامة المنشور يمنع «؟» نهائيًا، ولو سُحبت جملة مثل
    «تصحيح أم موجة جديدة؟ 🤔» لقتل الخبر الصحيح كليًا عند الفحص.
    وذاكرة key تضمن ألا تتكرر نفس الجملة حرفيًا بين منشورين متتاليين
    (كان القارئ يرى نفس «باختصار» مرتين متتاليتين لأن كل فئة كان بقالبَين فقط).
    """
    safe = [o for o in options if "?" not in o and "؟" not in o]
    pool = safe or list(options)
    if key and len(pool) > 1:
        trimmed = [o for o in pool if o != _LAST_PICK.get(key)]
        if trimmed:
            pool = trimmed
    choice = random.choice(pool)
    if key:
        _LAST_PICK[key] = choice
    return choice


# ------------------------------------------------------------ خبر عادي
def format_post(item) -> str | None:
    """منشور الخبر الكامل — بلا أي روابط، جاهز كـ caption مع الصورة."""
    cat = CATEGORIES[item.category]
    hook = _pick(cat["hooks"], f"{item.category}:hook")
    why = _pick(cat["why"], f"{item.category}:why")
    facts = item.facts or []
    ar_title = esc(item.title_ar)

    lines = [
        f'{cat["emoji"]} <b>{cat["label"]}</b> — {hook}',
        "",
        f"<b>{ar_title}</b>",
        "",
        f"⚡ <b>باختصار:</b> {why}",
    ]
    if facts:
        lines.append("")
        lines.append("📌 <b>بالأرقام:</b>")
        lines.extend(facts)

    # التذييل: الوقت + وسم القناة — بلا أسماء مصادر وبلا روابط نهائيًا
    rel = rel_time_ar(item.timestamp)
    if rel:
        lines.append("")
        lines.append(f"⏱️ {rel}")
    if CHANNEL_TAG:
        lines.append(esc(CHANNEL_TAG))

    msg = "\n".join(lines)
    # مع الصورة التسمية محدودة بـ 1024 — قصّر «باختصار» عند الحاجة
    if len(msg) > 1000 and why:
        overflow = len(msg) - 1000
        why_short = why[: max(60, len(why) - overflow - 3)].rsplit(" ", 1)[0] + "…"
        msg = msg.replace(why, why_short)
    return msg


# ------------------------------------------------------------ خبر حيتان جاهز
def whale_post(item) -> str:
    wd = item.whale_data
    cat = CATEGORIES["whale"]
    coin_ar = COIN_AR.get(wd["symbol"], wd["symbol"])

    if "بورصة" in wd["to_txt"]:
        direction = "to_exchange"
    elif "بورصة" in wd["from_txt"]:
        direction = "from_exchange"
    else:
        direction = "unknown"

    title = (f"حوت ينقل {wd['amount']:,.0f} {coin_ar} "
             f"(≈ {human_usd(wd['amount_usd'])}) من {wd['from_txt']} إلى {wd['to_txt']}")
    hook = _pick(cat["hooks"], "whale:hook")
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
    lines.extend(item.facts or [])
    lines.append("")
    lines.append(f"⏱️ {rel_time_ar(item.timestamp) or 'الآن'}")
    if CHANNEL_TAG:
        lines.append(esc(CHANNEL_TAG))
    return "\n".join(lines)
