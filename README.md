# News Bot (Crypto & Macro) - GitHub Actions Edition

بوت أخبار الكريبتو والماكرو المالية، يعمل بالكامل على GitHub Actions (مجاني 100%).

## 🎯 ماذا يفعل البوت؟

- يفحص 16+ مصدر RSS كل 5 دقائق (CoinDesk, CoinTelegraph, CNBC, Federal Reserve...)
- يفلتر الأخبار المهمة (breaking / hack / etf / tech / market / whale / fed / trump / geopolitics)
- يترجم العناوين للعربية
- يرسلها لقناة تلغرام + للمستخدمين المسموحين
- يحفظ الأخبار المُرسلة في `sent_news.json` (يُcommit للريبو) لمنع التكرار

## 📦 الملفات

```
news-bot/
├── .github/workflows/
│   ├── news-bot.yml      # تشغيل كل 5 دقائق
│   └── keepalive.yml     # يمنع نوم الريبو
├── main.py               # الكود الرئيسي (معدّل لـ GA)
├── requirements.txt      # pytz + requests + Flask + feedparser
├── sent_news.json        # ذاكرة الأخبار المُرسلة
└── README.md
```

## 🔧 التعديلات على main.py

1. **وضع GitHub Actions** (`GITHUB_ACTIONS=true`):
   - شغل دورة واحدة فقط (no `while True`)
   - لا يبدأ Flask server
   - لا يضبط webhook
   - لا يبدأ threads
   - يخرج بعد الانتهاء

2. **تغيير مسار التخزين**:
   - على Render: `/tmp/` (كما كان)
   - على GitHub Actions: المجلد الحالي (ليُcommit للريبو)

3. **`requirements.txt`** يشمل: `pytz`, `requests`, `Flask`, `feedparser`

## 🚀 الإعداد

### 1. ارفع الملفات لريبو GitHub **public**

### 2. أضف Secrets في إعدادات الريبو

```
Settings → Secrets and variables → Actions → New repository secret
```

**المتغيرات المطلوبة:**

| Secret | القيمة | ملاحظة |
|--------|--------|--------|
| `TELEGRAM_BOT_TOKEN` | `123:ABC-DEF...` | من @BotFather |
| `TELEGRAM_CHAT_ID` | `123456789` | ID المالك (من @userinfobot) |
| `CHANNEL_ID` | `@your_channel` أو `-100xxx` | ID القناة |
| `CHANNEL_LINK` | `https://t.me/your_channel` | رابط القناة |
| `CHANNEL_NAME` | `📢 قناتي` | اسم القناة للعرض |
| `SEND_TO_CHANNEL` | `true` | تفعيل الإرسال للقناة |
| `TIMEZONE` | `Africa/Algiers` | التوقيت المحلي |

**متغيرات اختيارية (للتخزين في Gist بدل الريبو):**

| Secret | الوصف |
|--------|------|
| `GIST_ID_SENT_NEWS` | ID of gist for sent_news.json |
| `GIST_ID_SETTINGS` | ID of gist for settings.json |
| `GITHUB_TOKEN` | PAT مع صلاحية gist |

> إذا لم تضع GIST IDs، سيُحفظ `sent_news.json` في الريبو تلقائياً (commit بعد كل تشغيل).

### 3. أضف البوت كـ Administrator في القناة

مهم جداً! من إعدادات القناة → Administrators → Add Bot.

### 4. اختبار يدوي

من تبويب **Actions** → **News Bot** → **Run workflow**

شاهد الـ logs، يجب أن ترى:
```
🤖 Running in GitHub Actions mode (one-shot)
📰 إجمالي الأخبار: 150
  ✉️ [breaking] Bitcoin surges past...
  ✉️ [fed] Powell signals rate cut...
📊 النتائج:
   • إجمالي الأخبار: 150
   • أخبار مهمة: 8
   • تم إرسالها: 3
   • أُرسلت سابقاً: 5
✅ انتهى. سيتم التشغيل التالي بعد 5 دقائق.
```

## ⚠️ حدود GitHub Actions

- الحد الأدنى لـ cron: 5 دقائق
- قد يتأخر 5-15 دقيقة في الذروة
- الريبو **public**: دقائق غير محدودة ✅
- الريبو private: 2000 دقيقة/شهر ❌

## 🔄 التراجع لـ Render

الكود لا يزال يدعم Render! إذا أردت العودة:
1. ارفع `main.py` لـ Render (دون أي تعديل)
2. أضف نفس الـ env vars في Render
3. سيعمل `start_bot()` تلقائياً (لأن `GITHUB_ACTIONS` لن يكون true)

## استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| `ModuleNotFoundError: pytz` | تأكد أن `requirements.txt` يحتوي `pytz` |
| لا تصل أخبار | تأكد أن البوت admin في القناة + `SEND_TO_CHANNEL=true` |
| تكرار الأخبار | تأكد أن `sent_news.json` يُcommit للريبو |
| `chat not found` | `CHANNEL_ID` غلط، استخدم `@channel` أو `-100xxx` |
| Workflow لا يعمل تلقائياً | تأكد وجود commit على main خلال 60 يوم (keepalive.yml) |
