"""
📊 المؤشرات الأمريكية — رسم بياني احترافي بالعربية
يجلب بيانات حقيقية من yfinance ويرسم chart لـ SPX, NDQ, DJI
"""

import os
import io
import time
import logging
import tempfile
import traceback

import matplotlib
matplotlib.use('Agg')  # بدون واجهة رسومية — ضروري لـ GitHub Actions

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch
import numpy as np

# ═══════════════════════════════════════════════════════════
# إعداد الخطوط العربية
# ═══════════════════════════════════════════════════════════
_font_loaded = False

def _load_fonts():
    """تحميل خطوط عربية إن وُجدت"""
    global _font_loaded
    if _font_loaded:
        return

    # مسارات الخطوط المرشحة (حسب النظام)
    font_candidates = [
        '/usr/share/fonts/truetype/chinese/NotoSansSC[wght].ttf',
        '/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf',
        '/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/lxgw-wenkai/LXGWWenKai-Regular.ttf',
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                fm.fontManager.addfont(fp)
            except Exception:
                pass

    # تعيين الخط الافتراضي — يُغطي الإنجليزية + الرموز
    # ملاحظة: النص في الرسم بالإنجليزية (SPX, NDQ, DJI, أرقام)
    # لذلك DejaVu Sans كافٍ ومتوفر في GitHub Actions
    plt.rcParams['font.family'] = ['DejaVu Sans', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
    # كتم تحذيرات الخطوط غير الموجودة
    import warnings
    warnings.filterwarnings('ignore', message='.*findfont.*')
    import logging
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)
    _font_loaded = True


_load_fonts()

log = logging.getLogger("NewsBot")

# ═══════════════════════════════════════════════════════════
# المؤشرات وتعريفاتها
# ═══════════════════════════════════════════════════════════
INDICES = {
    "SPX": {
        "ticker": "^GSPC",
        "name": "S&P 500",
        "color": "#2196F3",     # أزرق
        "color_fill": "#2196F320",
    },
    "NDQ": {
        "ticker": "^IXIC",
        "name": "Nasdaq",
        "color": "#4CAF50",     # أخضر
        "color_fill": "#4CAF5020",
    },
    "DJI": {
        "ticker": "^DJI",
        "name": "Dow Jones",
        "color": "#FF9800",     # برتقالي
        "color_fill": "#FF980020",
    },
}

CHART_PERIOD = "5d"     # آخر 5 أيام (يومياً)
CHART_INTERVAL = "1d"


# ═══════════════════════════════════════════════════════════
# جلب البيانات من yfinance
# ═══════════════════════════════════════════════════════════
def fetch_indices_data() -> dict:
    """
    جلب بيانات المؤشرات الثلاثة.
    يرجع: {
        "SPX": {"dates": [...], "prices": [...], "change": +1.5, "price": 5432.1},
        "NDQ": {...},
        "DJI": {...},
    }
    """
    try:
        import yfinance as yf
    except ImportError:
        log.error("❌ yfinance not installed — run: pip install yfinance")
        return {}

    results = {}
    for key, idx in INDICES.items():
        try:
            ticker = yf.Ticker(idx["ticker"])
            hist = ticker.history(period=CHART_PERIOD, interval=CHART_INTERVAL)

            if hist.empty:
                log.warning(f"📊 No data for {key} ({idx['ticker']})")
                continue

            dates = hist.index.tolist()
            closes = hist['Close'].tolist()

            if len(closes) < 2:
                continue

            current = closes[-1]
            previous = closes[-2] if len(closes) >= 2 else closes[0]
            change_pct = ((current - previous) / previous) * 100

            results[key] = {
                "dates": dates,
                "prices": closes,
                "current": round(current, 2),
                "change": round(change_pct, 2),
            }
            log.info(f"📊 {key}: {current:.2f} ({change_pct:+.2f}%)")

        except Exception as e:
            log.warning(f"📊 Failed to fetch {key}: {e}")

    return results


# ═══════════════════════════════════════════════════════════
# رسم البياني
# ═══════════════════════════════════════════════════════════
def create_chart(data: dict) -> str:
    """
    إنشاء رسم بياني احترافي.
    يرجع مسار الملف المؤقت أو سلسلة base64.
    """
    if not data:
        return ""

    fig, ax = plt.subplots(figsize=(14, 7), dpi=120)
    fig.patch.set_facecolor('#0D1117')
    ax.set_facecolor('#0D1117')

    for key, idx in INDICES.items():
        if key not in data:
            continue

        d = data[key]
        prices = np.array(d["prices"])
        dates = d["dates"]

        # رسم الخط
        ax.plot(dates, prices, color=idx["color"], linewidth=2.5,
                label=f'{key} {idx["name"]}', zorder=3)

        # تعبئة تحت الخط
        ax.fill_between(dates, prices, prices.min() * 0.998,
                        color=idx["color"], alpha=0.08, zorder=2)

        # نقطة النهاية (السعر الحالي)
        ax.scatter([dates[-1]], [prices[-1]], color=idx["color"],
                   s=80, zorder=5, edgecolors='white', linewidths=1.5)

        # ملصق السعر عند النقطة الأخيرة
        change = d["change"]
        arrow = "▲" if change >= 0 else "▼"
        label_text = f'{arrow} {d["current"]:,.2f} ({change:+.2f}%)'
        text_color = idx["color"]

        # تحديد موقع النص (فوق أو تحت)
        y_offset = prices[-1] * 0.005
        va = 'bottom' if change >= 0 else 'top'
        y_pos = prices[-1] + y_offset if change >= 0 else prices[-1] - y_offset

        ax.annotate(
            label_text,
            xy=(dates[-1], prices[-1]),
            xytext=(10, 15 if change >= 0 else -15),
            textcoords='offset points',
            fontsize=10, fontweight='bold', color=text_color,
            va=va, ha='left',
            arrowprops=dict(arrowstyle='-', color=text_color, lw=0.8),
        )

    # تنسيق المحاور
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(fontsize=9, color='#8B949E', rotation=0)
    plt.yticks(fontsize=9, color='#8B949E')

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f'{x:,.0f}'
    ))

    # شبكة
    ax.grid(True, alpha=0.15, color='#30363D', linestyle='--')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('#30363D')
    ax.spines['left'].set_color('#30363D')

    # عنوان الرسم
    ax.set_title(
        'US Market Indices  |  SPX · NDQ · DJI',
        fontsize=16, fontweight='bold', color='#E6EDF3',
        pad=20, loc='center'
    )

    # إضافة وسوم الألوان في الأسفل
    legend = ax.legend(
        loc='lower left', fontsize=10,
        framealpha=0.3, facecolor='#161B22', edgecolor='#30363D',
        labelcolor='#E6EDF3'
    )

    # إضافة watermark
    fig.text(0.99, 0.01, '@newscrypto1m', fontsize=8,
             color='#484F58', ha='right', va='bottom', alpha=0.7)

    # تعبئة الرسم
    plt.tight_layout(pad=1.5)

    # حفظ في ملف مؤقت
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False, prefix='market_')
    tmp_path = tmp.name
    tmp.close()

    fig.savefig(tmp_path, bbox_inches='tight', facecolor=fig.get_facecolor(),
                dpi=120, format='png')
    plt.close(fig)

    log.info(f"📊 Chart saved: {tmp_path} ({os.path.getsize(tmp_path)} bytes)")
    return tmp_path


# ═══════════════════════════════════════════════════════════
# بناء نص منشور المؤشرات
# ═══════════════════════════════════════════════════════════
def build_market_post(data: dict) -> str:
    """بناء نص المنشور بالعربية"""
    if not data:
        return ""

    lines = ["⚡ المؤشرات الأمريكية — آخر تحديث", ""]

    for key in ["SPX", "NDQ", "DJI"]:
        if key not in data:
            continue
        d = data[key]
        idx = INDICES[key]
        arrow = "📈" if d["change"] >= 0 else "📉"
        direction = "صعوداً" if d["change"] >= 0 else "هبوطاً"
        lines.append(
            f"{arrow} {idx['name']} ({key}): {d['current']:,.2f} — {direction} {abs(d['change']):.2f}%"
        )

    lines.append("")
    lines.append("📊 ترقبوا تطورات الجلسة وتأثيرها على سوق العملات الرقمية")
    lines.append("")
    lines.append("@newscrypto1m")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# الدورة الكاملة: جلب → رسم → إرسال
# ═══════════════════════════════════════════════════════════
async def run_market_update(send_func) -> bool:
    """
    جلب بيانات المؤشرات ورسم chart وإرسالها.
    send_func: دالة async(text, image_path_or_url) → bool
    """
    log.info("📊 Starting market indices update...")

    # 1) جلب البيانات
    data = fetch_indices_data()
    if not data:
        log.info("📊 No market data available — skipping")
        return False

    # 2) رسم البياني
    chart_path = create_chart(data)
    if not chart_path:
        log.warning("📊 Failed to create chart")
        return False

    # 3) بناء النص
    post_text = build_market_post(data)
    if not post_text:
        os.unlink(chart_path)
        return False

    # 4) إرسال
    try:
        ok = await send_func(post_text, chart_path, is_file=True)
        if ok:
            log.info("📊 Market update sent successfully")
        else:
            log.warning("📊 Failed to send market update")
    except Exception as e:
        log.error(f"📊 Market update error: {e}")
        ok = False
    finally:
        # تنظيف الملف المؤقت
        try:
            os.unlink(chart_path)
        except Exception:
            pass

    return ok
