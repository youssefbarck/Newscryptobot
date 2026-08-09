# 🐋 Crypto News Bot

بوت يلتقط أخبار الكريبتو والعملات الرقمية وشخصياتها الكبار (Saylor, CZ, Buterin, Musk) من مصادر متعددة، يترجمها للعربية مع الحفاظ على الأسماء والتوكنات، وينشرها في قناة تيليجرام.

## ✨ الميزات

- ✅ **جلب من 6 مصادر** (CoinDesk, Cointelegraph, Google News للشخصيات)
- ✅ **ترجمة عربية** مع الحفاظ على الأسماء والتوكنات بالإنجليزية
- ✅ **صورة أصلية** من الخبر (من حقل media:content في RSS)
- ✅ **تنسيق نظيف** — عنوان واضح + نقاط + وسم القناة فقط
- ✅ **منع التكرار** — هاش + Jaccard similarity (65%)
- ✅ **حفظ الهاشات** في ملف `sent_news.json` يُcommit تلقائياً
- ✅ **تشغيل كل 30 دقيقة** عبر GitHub Actions (مجاني)

## 📁 بنية المشروع

```
whale-news-bot/
├── .github/
│   └── workflows/
│       └── cron.yml          # GitHub Actions schedule
├── bot.py                    # المنسق الرئيسي
├── sources.py                # جلب RSS
├── translator.py             # Google Translate + حماية الكيانات
├── formatter.py              # تنسيق المنشور
├── dedup.py                  # منع التكرار
├── config.py                 # الإعدادات
├── requirements.txt          # المكتبات
├── README.md
├── .gitignore
└── sent_news.json            # يُنشأ تلقائياً
```

## 🔧 الإعداد

### 1) أنشئ repository على GitHub وارفع الملفات

```bash
cd whale-news-bot
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/USERNAME/whale-news-bot.git
git push -u origin main
```

### 2) احصل على Telegram Bot Token

1. افتح تيليجرام وتحدث مع [@BotFather](https://t.me/BotFather)
2. أرسل `/newbot` واتبع التعليمات
3. انسخ الـ Token

### 3) احصل على Channel Chat ID

1. أضف البوت كمشرف في قناتك
2. أرسل أي رسالة في القناة
3. افتح هذا الرابط (استبدل TOKEN و USERNAME):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. ابحث عن `"chat":{"id":-1001234567890}` وانسخ الرقم (يجب أن يبدأ بـ `-100`)

### 4) أضف GitHub Secrets

في صفحة الريبو: **Settings → Secrets and variables → Actions → New repository secret**

| الاسم | القيمة |
|---|---|
| `TELEGRAM_BOT_TOKEN` | التوكن من BotFather |
| `TELEGRAM_CHAT_ID` | معرّف القناة (يبدأ بـ `-100`) |

### 5) فعّل GitHub Actions

1. اذهب لتبويب **Actions** في الريبو
2. إذا ظهر تحذير "Workflows aren't being run" → اضغط **"I understand my workflows, go ahead and enable them"**

### 6) اختبار يدوي

في تبويب **Actions** → اختر **"Crypto News Bot"** → اضغط **"Run workflow"**

## 📝 تنسيق المنشور

```
عنوان الخبر المترجم

• نقطة أولى من الملخص
• نقطة ثانية من الملخص
• نقطة ثالثة من الملخص

@newscrypto1m
```

مرفق بصورة الخبر الأصلية.

## 🛡️ الحماية المُطبّقة على الأسماء

هذه الكيانات تُحفظ بالإنجليزية ولا تُترجم:

- **الشخصيات**: Michael Saylor, CZ, Vitalik Buterin, Elon Musk, Jerome Powell, Gary Gensler, Brian Armstrong, Brad Garlinghouse, Janet Yellen, Sam Bankman-Fried, Jack Dorsey, Cathie Wood
- **الشركات**: MicroStrategy, BlackRock, Fidelity, Grayscale, Binance, Coinbase, Kraken, Bybit, OKX, Tesla, SpaceX, Galaxy Digital, Blockstream, Bitwise, VanEck, Invesco
- **صناديق ETF**: IBIT, FBTC, GBTC, ETHA, EZET
- **العملات**: Bitcoin, Ethereum, Solana, Ripple, Cardano, Dogecoin, Avalanche, Polkadot, Chainlink, Polygon, Litecoin, Tron, Uniswap, Aave, Stellar, Hedera, Cosmos, Toncoin, Binance Coin, Tether, USDT, USDC, Shiba Inu, Pepe, Worldcoin, Near Protocol, Aptos, Arbitrum, Optimism, Sui
- **التوكنات**: BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, DOT, LINK, MATIC, LTC, TRX, UNI, AAVE, NEAR, APT, ARB, OP, SUI, SEI, TON, ATOM, XLM, HBAR, USDT, USDC, DAI, SHIB, PEPE, WLD, TIA, INJ, RNDR, RENDER, FET, RUNE, GMX, DYDX, EIGEN, ETHFI, PENDLE, JTO, JUP, RAY, BONK, WIF, FLOKI, IBIT, FBTC, GBTC, ETHA, EZET
- **مصطلحات**: DeFi, NFT, NFTs, Web3, DAO, ICO, ETF, ETFs, Spot ETF, Layer 1, Layer 2, Mainnet, Testnet, Federal Reserve, Fed, SEC, CFTC, FOMC, CPI, GDP, Bull Run, Bear Market

## 🔧 التخصيص

لتعديل الإعدادات، حرر `config.py`:

- `MAX_POSTS_PER_RUN` — عدد المنشورات لكل دورة (افتراضي 3)
- `MAX_NEWS_AGE_HOURS` — أقصى عمر للخبر بالساعات (افتراضي 6)
- `SIMILARITY_THRESHOLD` — عتبة التشابه (افتراضي 0.65)
- `MAX_BULLETS` — أقصى عدد نقاط في المنشور (افتراضي 4)
- `RSS_SOURCES` — إضافة/حذف مصادر
- `PROTECTED_NAMES` — إضافة كيانات تحمى من الترجمة

## 📊 المراقبة

- **Logs**: تبويب Actions → اختر آخر run → اضغط على step "Run bot"
- **الملف**: `sent_news.json` يُحدّث بعد كل دورة ويعرض عدد الهاشات
