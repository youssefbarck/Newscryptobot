"""
📊 المؤشرات الأمريكية — عرض قائمة بالأرقام والتغييرات
يجلب بيانات حقيقية من yfinance لـ DJI, SPX, NDQ
يُرسل فقط عند افتتاح وإغلاق السوق الأمريكي
"""

import os
import io
import time
import logging
import tempfile
import traceback
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as patches
import numpy as np

# ═══════════════════════════════════════════════════════════
# إعداد الخطوط
# ═══════════════════════════════════════════════════════════
_font_loaded = False

def _load_fonts():
    global _font_loaded
    if _font_loaded:
        return

    font_candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                fm.fontManager.addfont(fp)
            except Exception:
                pass

    plt.rcParams['font.family'] = ['DejaVu Sans', 'Liberation Sans', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False

    import warnings
    warnings.filterwarnings('ignore', message='.*findfont.*')
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)
    _font_loaded = True

_load_fonts()

log = logging.getLogger("NewsBot")

# ═══════════════════════════════════════════════════════════
# تعريفات المؤشرات
# ═══════════════════════════════════════════════════════════
INDICES = {
    "DJI": {
        "ticker": "^DJI",
        "name": "Dow Jones Industrial",
        "badge_num": "30",
        "badge_color": "#1E88E5",
        "value_color": "#E3F2FD",
    },
    "SPX": {
        "ticker": "^GSPC",
        "name": "S&P 500",
        "badge_num": "500",
        "badge_color": "#E53935",
        "value_color": "#FFEBEE",
    },
    "NDQ": {
        "ticker": "^IXIC",
        "name": "Nasdaq 100",
        "badge_num": "100",
        "badge_color": "#00ACC1",
        "value_color": "#E0F7FA",
    },
}

# ترتيب العرض في الصورة
DISPLAY_ORDER = ["DJI", "SPX", "NDQ"]


# ═══════════════════════════════════════════════════════════
# جلب البيانات من yfinance
# ═══════════════════════════════════════════════════════════
def fetch_indices_data() -> dict:
    """
    جلب البيانات الحالية للمؤشرات.
    يرجع: {
        "DJI": {"current": 52511.25, "change": 559.05, "change_pct": 1.08},
        ...
    }
    """
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed")
        return {}

    results = {}

    for key in DISPLAY_ORDER:
        idx = INDICES[key]
        try:
            ticker = yf.Ticker(idx["ticker"])
            # جلب بيانات آخر يومين لحساب التغيير
            hist = ticker.history(period="2d", interval="1d")

            if hist.empty or len(hist) < 1:
                log.warning(f"No data for {key}")
                continue

            current = hist['Close'].iloc[-1]

            if len(hist) >= 2:
                previous = hist['Close'].iloc[-2]
                change = current - previous
                change_pct = (change / previous) * 100
            else:
                change = 0
                change_pct = 0

            results[key] = {
                "current": round(float(current), 2),
                "change": round(float(change), 2),
                "change_pct": round(float(change_pct), 2),
            }
            log.info(f"{key}: {current:.2f} ({change_pct:+.2f}%)")

        except Exception as e:
            log.warning(f"Failed to fetch {key}: {e}")

    return results


# ═══════════════════════════════════════════════════════════
# إنشاء صورة عرض القائمة
# ═══════════════════════════════════════════════════════════
def create_list_image(data: dict, session_type: str = "open") -> str:
    """
    إنشاء صورة عرض قائمة احترافية.
    session_type: "open" أو "close"
    يرجع مسار الملف المؤقت.
    """
    if not data:
        return ""

    fig, ax = plt.subplots(figsize=(8, 5.5), dpi=200)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    # ═══════════════════════════════════════════════
    # العنوان
    # ═══════════════════════════════════════════════
    ax.text(5, 9.3, 'US Market Indices', ha='center', va='center',
            color='white', fontsize=22, fontweight='bold', fontfamily='DejaVu Sans')
    ax.text(5, 8.7, 'DJI  ·  SPX  ·  NDQ', ha='center', va='center',
            color='#8b949e', fontsize=13, fontfamily='DejaVu Sans')

    # حالة السوق (افتتاح / إغلاق)
    now_utc = datetime.now(timezone.utc)
    # تحويل إلى توقيت شرق أمريكا (ET)
    eastern = timezone(timedelta(hours=-4))  # EDT (صيفي)
    now_et = now_utc.astimezone(eastern)

    if session_type == "open":
        status_text = f'Market Open  |  {now_et.strftime("%b %d, %Y")}'
        status_color = '#58a6ff'
    else:
        status_text = f'Market Close  |  {now_et.strftime("%b %d, %Y")}'
        status_color = '#f0883e'

    ax.text(5, 8.15, status_text, ha='center', va='center',
            color=status_color, fontsize=11, fontfamily='DejaVu Sans', fontstyle='italic')

    # خط فاصل تحت العنوان
    ax.plot([1, 9], [7.75, 7.75], color='#30363d', linewidth=1.2, zorder=2)

    # ═══════════════════════════════════════════════
    # بطاقات المؤشرات
    # ═══════════════════════════════════════════════
    y_positions = [6.5, 4.5, 2.5]

    for i, key in enumerate(DISPLAY_ORDER):
        if key not in data:
            continue

        idx = INDICES[key]
        d = data[key]
        y = y_positions[i]

        # خلفية البطاقة
        card = patches.FancyBboxPatch(
            (0.8, y - 1.0), 8.4, 2.0,
            boxstyle='round,pad=0.15',
            facecolor='#161b22', edgecolor='#30363d',
            linewidth=0.8, zorder=1
        )
        ax.add_patch(card)

        # دائرة ملونة بالرقم
        circle = plt.Circle((1.8, y), 0.55, color=idx['badge_color'], zorder=3)
        ax.add_patch(circle)
        ax.text(1.8, y, idx['badge_num'], ha='center', va='center',
                color='white', fontsize=13, fontweight='bold',
                fontfamily='DejaVu Sans', zorder=4)

        # رمز المؤشر (tickr)
        ax.text(3.0, y + 0.35, key, ha='left', va='center',
                color='white', fontsize=17, fontweight='bold',
                fontfamily='DejaVu Sans')

        # الاسم الكامل
        ax.text(3.0, y - 0.25, idx['name'], ha='left', va='center',
                color='#8b949e', fontsize=10, fontfamily='DejaVu Sans')

        # القيمة الحالية (كبيرة)
        current_str = f"{d['current']:,.2f}"
        ax.text(9.0, y + 0.35, current_str, ha='right', va='center',
                color='white', fontsize=17, fontweight='bold',
                fontfamily='DejaVu Sans Mono')

        # التغيير + النسبة
        arrow = "\u25B2" if d['change_pct'] >= 0 else "\u25BC"
        change_color = '#66BB6A' if d['change_pct'] >= 0 else '#EF5350'
        sign = "+" if d['change_pct'] >= 0 else ""

        change_text = f"{arrow} {sign}{d['change']:,.2f}  ({sign}{d['change_pct']:.2f}%)"
        ax.text(9.0, y - 0.30, change_text, ha='right', va='center',
                color=change_color, fontsize=11, fontfamily='DejaVu Sans')

    # ═══════════════════════════════════════════════
    # علامة القناة
    # ═══════════════════════════════════════════════
    fig.text(0.98, 0.04, '@newscrypto1m', ha='right', va='bottom',
             color='#484f58', fontsize=10, fontfamily='DejaVu Sans',
             fontstyle='italic')

    # حفظ الملف
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False, prefix='market_')
    tmp_path = tmp.name
    tmp.close()

    plt.savefig(tmp_path, dpi=200, bbox_inches='tight',
                facecolor=fig.get_facecolor(), edgecolor='none', pad_inches=0.3)
    plt.close(fig)

    log.info(f"List image saved: {tmp_path} ({os.path.getsize(tmp_path)} bytes)")
    return tmp_path


# ═══════════════════════════════════════════════════════════
# بناء نص المنشور بالعربية
# ═══════════════════════════════════════════════════════════
def build_market_post(data: dict, session_type: str = "open") -> str:
    """بناء نص المنشور بالعربية"""
    if not data:
        return ""

    if session_type == "open":
        lines = [
            "⚡ المؤشرات الأمريكية عند الافتتاح",
            "",
        ]
    else:
        lines = [
            "📊 المؤشرات الأمريكية عند الإغلاق",
            "",
        ]

    for key in DISPLAY_ORDER:
        if key not in data:
            continue
        d = data[key]
        idx = INDICES[key]
        arrow = "▲" if d['change_pct'] >= 0 else "▼"
        direction = "صعوداً" if d['change_pct'] >= 0 else "هبوطاً"
        sign = "+" if d['change_pct'] >= 0 else ""
        lines.append(
            f"{arrow} {idx['name']} ({key}): {d['current']:,.2f} — {direction} {abs(d['change_pct']):.2f}%"
        )

    if session_type == "open":
        lines.append("")
        lines.append("📈 ترقبوا تطورات الجلسة وتأثيرها على سوق الكريبتو")
    else:
        lines.append("")
        lines.append("📋 ملخص الجلسة — ترقبوا التحليل غداً")

    lines.append("")
    lines.append("@newscrypto1m")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# الدورة الكاملة: جلب → رسم → إرسال
# ═══════════════════════════════════════════════════════════
async def run_market_update(send_func, session_type: str = "open") -> bool:
    """
    جلب بيانات المؤشرات وإنشاء صورة القائمة وإرسالها.
    send_func: دالة async(text, image, is_file) → bool
    session_type: "open" أو "close"
    """
    label = "الافتتاح" if session_type == "open" else "الإغلاق"
    log.info(f"📊 Starting market update ({label})...")

    # 1) جلب البيانات
    data = fetch_indices_data()
    if not data:
        log.info("📊 No market data — skipping")
        return False

    # 2) إنشاء صورة القائمة
    chart_path = create_list_image(data, session_type=session_type)
    if not chart_path:
        log.warning("📊 Failed to create image")
        return False

    # 3) بناء النص
    post_text = build_market_post(data, session_type=session_type)
    if not post_text:
        try:
            os.unlink(chart_path)
        except Exception:
            pass
        return False

    # 4) إرسال
    try:
        ok = await send_func(post_text, chart_path, is_file=True)
        if ok:
            log.info(f"📊 Market {label} update sent successfully")
        else:
            log.warning(f"📊 Failed to send market {label} update")
    except Exception as e:
        log.error(f"📊 Market {label} error: {e}")
        ok = False
    finally:
        try:
            os.unlink(chart_path)
        except Exception:
            pass

    return ok
