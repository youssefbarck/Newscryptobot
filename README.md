# 🔴 مشكلة "البوت اليتيم" — التشخيص الكامل والحل

## 📋 ما الذي يحدث بالضبط؟

GitHub Actions لديها قاعدة صارمة غير معلنة بوضوح:

> **الـ scheduled workflows تُوقف تلقائياً في حالتين:**
> 1. **60 يوم بدون أي commit** على الريبو (في الـ repos العامة).
> 2. **بعد كل fork** لريبو عام (الـ scheduled workflows تُعطّل في الـ fork).

يعني حتى لو `cron: '*/30 * * * *'` موجود في YAML ويعمل، **بعد 60 يوم من الهدوء، GitHub يوقفه** — ولا يستيقظ ثانيةً مهما طال الانتظار.

علاوة على ذلك، حتى لو الـ cron ما زال مفعّلاً، **GitHub يأخر التشغيل في فترات الذروة** (بداية كل ساعة تحديداً):

> *"The `schedule` event can be delayed during periods of high loads of GitHub Actions workflow runs. High load times include the start of every hour."* — توثيق GitHub الرسمي

`*/30 * * * *` يعني `0,30` — وهي **أسوأ دقيقتين ممكنتين** (بداية الساعة ونصفها يصطدم مع ملايين cron jobs أخرى).

---

## 🩹 الحل المُطبَّق في هذه الحزمة (4 طبقات حماية)

### الطبقة 1 — تصحيح توقيت الـ cron (تفادي الذروة)

**الملف**: `.github/workflows/news.yml`

غيّرنا `0,30` → `7,37` (نفس التردد، لكن خارج ذروة بداية الساعة):

```yaml
on:
  schedule:
    - cron: '7,37 * * * *'   # بدل '0,30 * * * *'
```

هذا وحده يحل ~70% من حالات "لا يستيقظ".

### الطبقة 2 — Keep-Alive يومي يمنع إيقاف الـ cron بعد 60 يوم

**الملف**: `.github/workflows/keep-alive.yml`

يومياً الساعة 03:17 UTC، يعمل commit بسيط يحدّث ملف `daily_keepalive.txt`. هذا يُحسب كنشاط على الريبو → GitHub لا يوقف الـ cron.

### الطبقة 3 — مراقبة + تنبيه تلقائي

**الملف**: `.github/workflows/monitor.yml`

يومياً الساعة 08:42 UTC، يفحص آخر تشغيل لـ `news.yml`. لو:
- مضت أكثر من ساعتان دون تشغيل ناجح، **أو**
- آخر تشغيل انتهى بفشل، **أو**
- لا يوجد أي تشغيل سابق على الإطلاق،

→ يُنشئ **issue** على الريبو بعنوان `🚨 Crypto Bot Monitor: <reason>` لتنبيهك فوراً.

### الطبقة 4 — External trigger من cron-job.org (الأقوى)

**الملف**: `.github/workflows/trigger-bot.yml`

هذا workflow "مستقبِل" فقط. عند استدعائه من خارج GitHub (عبر `repository_dispatch` أو `workflow_dispatch`)، يطلق `news.yml`.

نضبط خدمة خارجية مجانية (cron-job.org) لتنفّذ هذا الطلب يومياً — حتى لو GitHub أوقف كل crons الداخلية، الـ trigger الخارجي يعمل.

> **لماذا الطبقة 4 مهمة؟** لأنها الحل الوحيد الذي ينجو من إيقاف GitHub نفسه للـ scheduled workflows. كل ما عداها يعتمد على GitHub، الذي قد يوقف cron لأي سبب.

---

## 🚀 خطوات التطبيق (افعلها بالترتيب)

### 1) انسخ ملفات الـ workflows لمشروعك

```bash
# من جذر الريبو
cp -r .github/workflows/* YOUR_REPO/.github/workflows/
```

الملفات المطلوبة:
- `news.yml` (البوت نفسه)
- `keep-alive.yml` (منع الإيقاف)
- `monitor.yml` (المراقبة)
- `trigger-bot.yml` (المستقبِل الخارجي)
- `scripts/health_check.py` (فحص تشخيصي اختياري)

### 2) Commit + Push

```bash
git add .github/workflows/ scripts/
git commit -m "feat: add bot workflows with anti-orphan protection"
git push
```

### 3) أضف الـ Secrets المطلوبة

اذهب لـ `Settings → Secrets and variables → Actions → New repository secret`:

| Secret Name | القيمة | مطلوب؟ |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | التوكن من BotFather | ✅ |
| `TELEGRAM_CHAT_ID` | معرّف القناة (`-1001234567890`) | ✅ |
| `CRYPTOPANIC_API_KEY` | مفتاح CryptoPanic (إن وُجد) | اختياري |
| `COINGECKO_API_KEY` | مفتاح CoinGecko (إن وُجد) | اختياري |

### 4) فعّل الـ workflows يدوياً أول مرة

1. اذهب لـ `Actions` tab.
2. لو ترى أي workflow مع زر **"Enable workflow"** — اضغطه.
3. شغّل كل workflow يدوياً مرة واحدة عبر **"Run workflow"** للتأكد.

### 5) فعّل الطبقة 4 (cron-job.org) — اختياري لكن موصى به

اتبع دليل `docs/cron-job-org.md` لتفعيل الـ trigger الخارجي.

### 6) تأكد من صحة الإعدادات (Health Check)

شغّل الـ workflow `Crypto News Bot` يدوياً مع `debug_mode=true`:
- يفحص المتغيرات، الاتصال بـ Telegram، صلاحيات القناة، وحدات البوت.
- لا يرسل شيئاً للقناة.

أو شغّل السكريبت محلياً:
```bash
python scripts/health_check.py
```

---

## 🧪 كيف تتحقق أن الحل يعمل؟

بعد التطبيق، خلال **24 ساعة** يجب أن ترى:

| Workflow | عدد التشغيلات المتوقعة/24س |
|---|---|
| `news.yml` | ~48 (كل 30 دقيقة) |
| `keep-alive.yml` | 1 |
| `monitor.yml` | 1 |

راجع `Actions` tab → كل workflow → تأكد أن آخر تشغيل `success`.

لو `monitor.yml` أنشأ issue بـ `🚨 Crypto Bot Monitor` — يعني هناك مشكلة، اقرأ الـ issue للتشخيص.

---

## 📁 هيكل الملفات

```
YOUR_REPO/
├── .github/
│   ├── workflows/
│   │   ├── news.yml          ← البوت نفسه (كل 30 دقيقة)
│   │   ├── keep-alive.yml    ← منع الإيقاف (يومياً)
│   │   ├── monitor.yml       ← المراقبة (يومياً)
│   │   └── trigger-bot.yml   ← مستقبِل خارجي
│   └── state/                ← يُنشأ تلقائياً
│       ├── last_alive.json
│       └── daily_keepalive.txt
├── scripts/
│   └── health_check.py       ← فحص تشخيصي
└── docs/
    └── cron-job-org.md        ← دليل الطبقة 4
```

---

## 🎯 ملخص سريع

| المشكلة | الحل |
|---|---|
| GitHub يوقف cron بعد 60 يوم | `keep-alive.yml` يعمل commit يومي |
| الذروة في بداية الساعة تسبب تأخير/إسقاط | `cron: '7,37 * * * *'` بدل `0,30` |
| لا تعرف لو البوت توقف | `monitor.yml` ينشئ issue تلقائياً |
| GitHub نفسه يعطل كل crons | `trigger-bot.yml` + cron-job.org trigger خارجي |

**قبل**: البوت "يتيم" — مجدول لكن لا يستيقظ.
**بعد**: 4 طبقات حماية تضمن التشغيل المستمر + تنبيه فوري عند أي مشكلة.
