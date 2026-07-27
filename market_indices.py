"""
📊 مؤشرات السوق الأمريكية — US Market Indices
يجلب البيانات الحقيقية ويرسلها عبر Telegram
مصدر البيانات: Yahoo Finance (مع timeout و fallback)
"""

import os
import sys
import time
import asyncio
import traceback
from datetime import datetime, timezone, timedelta

import aiohttp
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.font_manager as fm

# ═══════════════════════════════════════════════════════════
# إعدادات
# ═══════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
CHANNEL_TAG        = "@newscrypto1m"

# المؤشرات
INDICES = {
    "DJI": {
        "ticker": "^DJI",
        "name": "Dow Jones Industrial",
        "badge": "30",
        "color": "#FF9800",
    },
    "SPX": {
        "ticker": "^GSPC",
        "name": "S&P 500",
        "badge": "500",
        "color": "#2196F3",
    },
    "NDQ": {
        "ticker": "^NDX",
        "name": "Nasdaq 100",
        "badge": "100",
        "color": "#00BCD4",
    },
}

# Font setup — safe loading
for font_path in [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]:
    if os.path.exists(font_path):
        fm.fontManager.addfont(font_path)
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


# ═══════════════════════════════════════════════════════════
# جلب البيانات — طريقة 1: API سريع (no yfinance)
# ═══════════════════════════════════════════════════════════
async def fetch_from_yahoo_api():
    """
    يجلب بيانات المؤشرات عبر Yahoo Finance API مباشرة
    أسرع بكثير من yfinance library
    """
    results = {}

    ticker_map = {
        "^DJI": "DJI",
        "^GSPC": "SPX",
        "^NDX": "NDQ",
    }

    try:
        async with aiohttp.ClientSession() as session:
            for ticker, symbol in ticker_map.items():
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
                headers = {"User-Agent": "Mozilla/5.0"}

                try:
                    async with session.get(url, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            print(f"❌ Yahoo API {ticker}: status {resp.status}")
                            results[symbol] = None
                            continue

                        json_data = await resp.json()

                        meta = json_data["chart"]["result"][0]["meta"]
                        price = meta["regularMarketPrice"]
                        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose", price)
                        change = price - prev_close
                        change_pct = (change / prev_close) * 100 if prev_close != 0 else 0

                        results[symbol] = {
                            "price": price,
                            "change": change,
                            "change_pct": change_pct,
                        }
                        print(f"✅ {symbol}: {price:,.2f} ({change:+,.2f} / {change_pct:+.2f}%)")

                except asyncio.TimeoutError:
                    print(f"⏰ Timeout fetching {ticker}")
                    results[symbol] = None
                except Exception as e:
                    print(f"❌ Error fetching {ticker}: {e}")
                    results[symbol] = None

    except Exception as e:
        print(f"❌ Yahoo API error: {e}")
        return None

    return results if all(v is not None for v in results.values()) else None


# ═══════════════════════════════════════════════════════════
# جلب البيانات — طريقة 2: yfinance (fallback)
# ═══════════════════════════════════════════════════════════
def fetch_from_yfinance():
    """طريقة بديلة باستخدام yfinance مع timeout"""
    try:
        import yfinance as yf

        results = {}
        tickers_list = [info["ticker"] for info in INDICES.values()]

        data = yf.download(tickers_list, period="5d", interval="1d",
                          auto_adjust=True, progress=False,
                          threads=False)

        if data.empty:
            print("❌ No data from yfinance")
            return None

        close_col = data['Close']
        open_col = data['Open']

        for symbol, info in INDICES.items():
            ticker = info["ticker"]
            try:
                if hasattr(close_col, 'columns') and ticker in close_col.columns:
                    price_series = close_col[ticker].dropna()
                    open_series = open_col[ticker].dropna()
                else:
                    price_series = close_col.iloc[:, 0].dropna()
                    open_series = open_col.iloc[:, 0].dropna()

                if len(price_series) == 0:
                    raise ValueError(f"No data for {ticker}")

                price = float(price_series.iloc[-1])
                open_price = float(open_series.iloc[-1]) if len(open_series) > 0 else price
                change = price - open_price
                change_pct = (change / open_price) * 100 if open_price != 0 else 0

                results[symbol] = {"price": price, "change": change, "change_pct": change_pct}
                print(f"✅ {symbol}: {price:,.2f} ({change:+,.2f} / {change_pct:+.2f}%)")
            except Exception as e:
                print(f"❌ yfinance error {symbol}: {e}")
                results[symbol] = None

        return results if all(v is not None for v in results.values()) else None

    except ImportError:
        print("⚠️ yfinance not installed")
        return None
    except Exception as e:
        print(f"❌ yfinance error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# جلب البيانات الرئيسي (يجرب API ثم yfinance)
# ═══════════════════════════════════════════════════════════
async def fetch_market_data():
    """يجرب Yahoo API أولاً (سريع)، ثم yfinance (بديل)"""
    # طريقة 1: Yahoo API (سريع - 5 ثواني)
    print("📡 Trying Yahoo API (fast)...")
    data = await fetch_from_yahoo_api()
    if data:
        return data

    # طريقة 2: yfinance (بديل)
    print("⚠️ API failed, trying yfinance (fallback)...")
    data = fetch_from_yfinance()
    if data:
        return data

    print("❌ All methods failed")
    return None


# ═══════════════════════════════════════════════════════════
# توليد صورة البطاقة
# ═══════════════════════════════════════════════════════════
def generate_card_image(data, session_type="open"):
    fig, ax = plt.subplots(figsize=(8, 5.5), dpi=200)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    if session_type == "open":
        title = "US Market — Open"
        subtitle = "Market Opening"
    else:
        title = "US Market — Close"
        subtitle = "Market Closing"

    ax.text(5, 9.2, title, ha='center', va='center',
            color='white', fontsize=20, fontweight='bold')
    ax.text(5, 8.55, subtitle, ha='center', va='center',
            color='#8b949e', fontsize=12)
    ax.plot([0.8, 9.2], [8.15, 8.15], color='#21262d', linewidth=1.2)

    rows_y = [7.0, 5.0, 3.0]
    symbols = ["DJI", "SPX", "NDQ"]

    for i, symbol in enumerate(symbols):
        y = rows_y[i]
        info = INDICES[symbol]
        d = data[symbol]
        color = info["color"]

        outer = patches.Circle((1.3, y), 0.45, facecolor=color, edgecolor='none', alpha=0.15)
        ax.add_patch(outer)
        inner = patches.Circle((1.3, y), 0.3, facecolor=color, edgecolor='none', alpha=0.9)
        ax.add_patch(inner)
        ax.text(1.3, y, info["badge"], ha='center', va='center', color='white', fontsize=8, fontweight='bold')
        ax.text(2.2, y + 0.15, symbol, ha='left', va='center', color='white', fontsize=15, fontweight='bold')
        ax.text(2.2, y - 0.25, info["name"], ha='left', va='center', color='#8b949e', fontsize=9)
        ax.text(7.0, y + 0.15, f"{d['price']:,.2f}", ha='right', va='center', color='white', fontsize=16, fontweight='bold')

        change = d['change']
        change_pct = d['change_pct']
        change_color = '#4CAF50' if change >= 0 else '#EF5350'
        arrow = '+' if change >= 0 else ''

        ax.text(9.0, y + 0.15, f"{arrow}{change:,.2f}", ha='right', va='center',
                color=change_color, fontsize=12, fontweight='bold')
        ax.text(9.0, y - 0.25, f"({arrow}{change_pct:.2f}%)", ha='right', va='center',
                color=change_color, fontsize=10)

        if i < 2:
            ax.plot([0.8, 9.2], [y - 0.7, y - 0.7], color='#21262d', linewidth=0.8)

    ax.plot([0.8, 9.2], [rows_y[2] - 0.7, rows_y[2] - 0.7], color='#21262d', linewidth=1.2)

    et_tz = timezone(timedelta(hours=-4))
    now_et = datetime.now(et_tz)
    date_str = now_et.strftime('%b %d, %Y - %H:%M ET')
    ax.text(5, 1.5, date_str, ha='center', va='center', color='#484f58', fontsize=10)
    ax.text(9.2, 0.6, CHANNEL_TAG, ha='right', va='center', color='#484f58', fontsize=10, fontstyle='italic')

    card = patches.FancyBboxPatch((0.5, 0.3), 9.0, 9.2, boxstyle='round,pad=0.2',
                                   facecolor='none', edgecolor='#30363d', linewidth=1.5)
    ax.add_patch(card)

    plt.tight_layout()
    image_path = f"/tmp/market_{session_type}.png"
    plt.savefig(image_path, dpi=200, bbox_inches='tight', facecolor='#0d1117', edgecolor='none', pad_inches=0.3)
    plt.close(fig)
    print(f"📸 Image saved: {image_path}")
    return image_path


# ═══════════════════════════════════════════════════════════
# صياغة نص المنشور
# ═══════════════════════════════════════════════════════════
def build_caption(data, session_type="open"):
    if session_type == "open":
        text = "⚡ المؤشرات الأمريكية عند الافتتاح\n\n"
    else:
        text = "🔚 المؤشرات الأمريكية عند الإغلاق\n\n"

    for symbol in ["DJI", "SPX", "NDQ"]:
        d = data[symbol]
        emoji = "📈" if d['change'] >= 0 else "📉"
        arrow = "▲" if d['change'] >= 0 else "▼"
        pct = f"+{d['change_pct']:.2f}%" if d['change'] >= 0 else f"{d['change_pct']:.2f}%"
        text += f"{emoji} {symbol}: {d['price']:,.2f}  {arrow} {pct}\n"

    text += f"\n@newscrypto1m"
    return text


# ═══════════════════════════════════════════════════════════
# إرسال الصورة عبر Telegram
# ═══════════════════════════════════════════════════════════
async def send_to_telegram(image_path, caption):
    if not os.path.exists(image_path):
        print(f"❌ Image not found: {image_path}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    try:
        async with aiohttp.ClientSession() as session:
            with open(image_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field("chat_id", TELEGRAM_CHAT_ID)
                data.add_field("photo", f, filename='market.png', content_type='image/png')
                data.add_field("caption", caption[:1024])

                async with session.post(url, data=data,
                                        timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        print("✅ Sent to Telegram!")
                        return True
                    else:
                        err = await resp.text()
                        print(f"❌ Telegram error: {err[:300]}")
                        return False
    except Exception as e:
        print(f"❌ Send error: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# التحقق
# ═══════════════════════════════════════════════════════════
def check_env():
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID")
    if errors:
        print(f"❌ Missing env vars: {', '.join(errors)}")
        return False
    return True


# ═══════════════════════════════════════════════════════════
# نقطة الدخول
# ═══════════════════════════════════════════════════════════
async def main(session_type="auto"):
    print("=" * 50)
    print(f"📊 US Market Indices — {session_type.upper()}")
    print("=" * 50)

    if not check_env():
        print("⚠️ Missing env vars — check GitHub Secrets")
        sys.exit(1)

    if session_type == "auto":
        et_tz = timezone(timedelta(hours=-4))
        now_et = datetime.now(et_tz)
        hour_et = now_et.hour
        session_type = "open" if hour_et < 13 else "close"
        print(f"🕐 Auto-detected session: {session_type}")

    print("\n📡 Fetching market data...")
    data = await fetch_market_data()
    if not data:
        print("❌ Failed to fetch market data")
        print("ℹ️ Market may be closed (weekends/holidays)")
        sys.exit(1)

    print("\n🎨 Generating card image...")
    image_path = generate_card_image(data, session_type)

    caption = build_caption(data, session_type)
    print(f"\n📝 Caption:\n{caption}")

    print("\n📤 Sending to Telegram...")
    ok = await send_to_telegram(image_path, caption)

    if ok:
        print(f"\n✅ Market indices post sent!")
    else:
        print(f"\n❌ Failed to send")
        sys.exit(1)


if __name__ == "__main__":
    session = sys.argv[1] if len(sys.argv) > 1 else "auto"
    asyncio.run(main(session))
