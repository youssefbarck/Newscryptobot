# Crypto & Macro News Bot

بوت يرسل الأخبار المهمة فقط إلى تلغرام كل 5 دقائق، يعمل بالكامل على GitHub Actions (مجاني 100%).

## 🎯 نطاق التغطية

البوت يفلتر الأخبار ويرسل فقط ما يقع في إحدى هذه الفئات:

| الفئة | الأمثلة |
|------|------|
| ₿ **كريبتو** | Bitcoin, Ethereum, ETFs, SEC, Binance, Coinbase, DeFi, NFT, Halving |
| 🏛 **تصريحات مسؤولين** | Jerome Powell, Christine Lagarde, Janet Yellen, Gary Gensler, Presidents, Treasury, Fed, ECB, IMF |
| 📈 **أسواق مالية** | S&P, Nasdaq, yields, inflation, CPI, jobs report, rate decisions |

## ⚙️ آلية العمل

1. كل 5 دقائق يجمع الأخبار من 14+ مصدر RSS
2. يصنّف كل خبر إلى (crypto / official / market) بناءً على الكلمات المفتاحية
3. يقبل الخبر فقط إذا:
   - تطابق مع كلمتين أو أكثر في إحدى الفئات، **أو**
   - احتوى على كلمة عاجلة (Breaking / عاجل) + تطابق واحد
4. يمنع التكرار عبر `state.json` (hash العنوان)
5. يرسل الأخبار مرتبة حسب درجة التطابق

## 📦 الملفات

```
news-bot/
├── .github/workflows/
│   ├── news-bot.yml      # تشغيل كل 5 دقائق
│   └── keepalive.yml     # يمنع نوم الريبو
├── bot.py                # الكود الرئيسي
├── requirements.txt
├── state.json
└── README.md
```

## 🚀 التثبيت

### 1. ارفع الملفات لريبو public على GitHub

### 2. أنشئ بوت تلغرام
- راسل **@BotFather** → `/newbot` → احفظ التوكن
- راسل **@userinfobot** → احصل على `CHAT_ID`
- (للقنوات) أضف البوت كـ administrator

### 3. أضف Secrets

```
Settings → Secrets and variables → Actions → New repository secret
```

| Name | Value |
|------|-------|
| `TELEGRAM_TOKEN` | `123456:ABC-DEF...` |
| `CHAT_ID` | `123456789` أو `@yourchannel` |

### 4. اختبار يدوي
تبويب **Actions** → **News Bot** → **Run workflow**

## 🔧 التخصيص

### إضافة مصادر RSS
عدّل القاموس `SOURCES` في `bot.py`:

```python
SOURCES = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    # أضف مصادرك هنا
}
```

### إضافة كلمات مفتاحية
عدّل المجموعات في `bot.py`:
- `CRYPTO_KEYWORDS_EN` / `CRYPTO_KEYWORDS_AR` — مصطلحات الكريبتو
- `OFFICIALS_KEYWORDS_EN` / `OFFICIALS_KEYWORDS_AR` — أسماء المسؤولين والمؤسسات
- `MARKET_KEYWORDS_EN` / `MARKET_KEYWORDS_AR` — مصطلحات الأسواق

### ضبط حساسية الفلتر
في الدالة `main()`:

```python
# تقليل الضجيج (إرسال أقل، جودة أعلى)
if score < 3 and "عاجل" not in (reason or ""):
    continue

# أو زيادة الحساسية (إرسال أكثر)
if score < 1 and "عاجل" not in (reason or ""):
    continue
```

## 📨 شكل الرسالة

```
₿ كريبتو  [CoinDesk]

BlackRock Files for Spot Ethereum ETF

🏷 السبب: عاجل + crypto
🕐 النشر: Sat, 12 Jul 2025 14:3

🔗 https://www.coindesk.com/...
```

## ⚠️ حدود GitHub Actions

- الحد الأدنى لـ cron: 5 دقائق
- قد يتأخر 5-15 دقيقة في الذروة
- الريبو public: دقائق غير محدودة ✅
- الريبو private: 2000 دقيقة/شهر ❌

## استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| لم تصل رسائل | قد لا توجد أخبار مهمة. جرّب تشغيل يدوي |
| رسائل كثيرة جداً | ارفع شرط `score` إلى 3 أو أكثر |
| رسائل قليلة جداً | اخفض شرط `score` إلى 1 |
| Flood limit | زد `SEND_DELAY` في `bot.py` |
| مصدر لا يعمل | تحقق من الرابط في المتصفح أولاً |
