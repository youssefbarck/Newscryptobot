# 🔴 دليل إعداد External Trigger عبر cron-job.org

هذا الدليل يشرح كيف تضبط خدمة cron-job.org المجانية لتوقظ البوت يومياً عبر `workflow_dispatch` API، حتى لو GitHub أوقف الـ scheduled workflows الداخلية.

---

## 📌 لماذا تحتاج هذا؟

GitHub Actions لها قاعدة صارمة:

> **الـ scheduled workflows تُوقف تلقائياً بعد 60 يوم بدون أي commit على الريبو** (للـ repos العامة).

يعني لو البوت لم يجد أخباراً جديدة لـ 60 يوم → لا commit → GitHub يوقف الـ cron → البوت لا يستيقظ ثانية.

الحل: **خدمة cron خارجية** (cron-job.org) تستدعي الـ workflow عبر API يومياً. هذا يضمن:
1. البوت يستيقظ حتى لو GitHub أوقف crons الداخلية.
2. الـ commit الناتج من البوت نفسه يُحسب كـ "نشاط" → يطيل عمر الـ cron الداخلية.

---

## 🛠️ المتطلبات

1. **حساب GitHub** مع الريبو الذي يحتوي على البوت.
2. **PAT (Personal Access Token)** بصلاحية `workflow` على الريبو.
3. **حساب cron-job.org** (مجاني تماماً، بدون بطاقة ائتمان).
4. **ملف `trigger-bot.yml`** مرفوع على الريبو (موجود في هذه الحزمة).

---

## الخطوة 1 — إنشاء Personal Access Token (PAT)

1. اذهب لـ: https://github.com/settings/tokens
2. اضغط **"Generate new token" → "Generate new token (classic)"** (أو "Fine-grained" — سنشرح كلاهما).

### الخيار أ) Classic PAT (أبسط):
- **Note**: `cron-job.org trigger`
- **Expiration**: 90 يوم (أو "No expiration" لو تفضّل)
- **Scopes**:
  - ✅ `workflow` (مطلوب — لتشغيل workflows)
  - ✅ `repo` (لو الريبو private؛ لو public فقط، يمكنك تخطيه)

3. اضغط **"Generate token"**.
4. **انسخ التوكن فوراً** (لن يظهر مرة ثانية!): `ghp_xxxxxxxxxxxxxxxxxxxx`

### الخيار ب) Fine-grained PAT (أكثر أماناً):
- **Resource owner**: حسابك
- **Repository access**: Only select repositories → اختر ريبو البوت فقط
- **Permissions**:
  - `Actions`: Read and write
  - `Metadata`: Read (تُضاف تلقائياً)
- **Expiration**: 90 يوم

---

## الخطوة 2 — تأكد أن `trigger-bot.yml` مرفوع

الملف يجب أن يكون في:
```
YOUR_REPO/.github/workflows/trigger-bot.yml
```

محتواه (موجود في الحزمة):
```yaml
name: Trigger Bot
on:
  repository_dispatch:
    types: [trigger_bot]
  workflow_dispatch:

jobs:
  trigger:
    runs-on: ubuntu-latest
    steps:
      - name: 🚀 Trigger news bot workflow
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh workflow run news.yml --repo "$GITHUB_REPOSITORY" --ref "${{ github.ref_name }}"
```

تأكد أن `news.yml` على نفس الفرع (`main` أو `master`).

---

## الخطوة 3 — إنشاء حساب على cron-job.org

1. اذهب لـ: https://cron-job.org/en/
2. اضغط **"Sign up"** (أعلى اليمين).
3. أدخل بريداً + كلمة مرور + تأكيد البريد.
4. سجّل الدخول.

> **ملاحظة**: cron-job.org مجاني تماماً حتى للاستخدام المكثف. لا يطلب بطاقة.

---

## الخطوة 4 — إنشاء cron job جديد

1. من لوحة التحكم، اضغط **"CREATE CRONJOB"** (أعلى اليسار).
2. املأ الحقول كالتالي:

### البيانات الأساسية

| الحقل | القيمة |
|---|---|
| **Title** | `Crypto Bot Trigger` |
| **URL** | `https://api.github.com/repos/USER/REPO/actions/workflows/trigger-bot.yml/dispatches` |
| **Execution Pattern** | منتظم (Fixed) |

**استبدل** `USER/REPO` باسم مستخدم GitHub + اسم الريبو.
مثال: `https://api.github.com/repos/octocat/news-bot/actions/workflows/trigger-bot.yml/dispatches`

### الجدولة

| الحقل | القيمة الموصى بها |
|---|---|
| **Execution Frequency** | Daily |
| **Time** | 06:00 UTC (أو أي وقت يناسبك) |

> **ملاحظة**: مرة/يوم تكفي لتفادي عتبة الـ 60 يوم. لو تريد تأكيداً أعلى، مرتين/يوم (مثلاً 06:00 و 18:00 UTC).

### إعدادات متقدمة (Advanced)

| الحقل | القيمة |
|---|---|
| **Request Method** | **POST** |
| **Request Headers** | (انظر أدناه) |
| **Request Body** | (انظر أدناه) |
| **Timeout (sec)** | 30 |
| **Failure Notification** | ✅ (إن وُجد) |

### Request Headers

أضف الـ headers التالية (كل واحد في سطر، صيغة `Key: Value`):

```
Authorization: Bearer ghp_xxxxxxxxxxxxxxxxxxxx
Accept: application/vnd.github+json
Content-Type: application/json
User-Agent: cron-job-org
```

> **استبدل** `ghp_xxx...` بالـ PAT الذي أنشأته في الخطوة 1.

### Request Body

```json
{"ref": "main"}
```

> استبدل `main` باسم فرعك الافتراضي لو اختلف (مثلاً `master`).

### Notifications (اختياري لكن موصى به)

- **Notify on failure**: ✅ فعّله
- **Email**: بريدك
- هذا يرسل لك إشعاراً لو الـ cron-job فشل (مثلاً PAT منتهي).

### Save

اضغط **"SAVE"** أسفل الصفحة.

---

## الخطوة 5 — اختبار يدوي

1. على لوحة cron-job.org، اضغط زر **"Run now"** (أيقونة البرق بجانب الـ job).
2. انتظر بضع ثوان.
3. اذهب لـ GitHub → `Actions` tab على الريبو.
4. يجب أن ترى workflow **"Trigger Bot"** بدأ تشغيله.
5. بداخله، خطوة **"🚀 Trigger news bot workflow"** ستنفذ `gh workflow run news.yml`.
6. بعد ثوانٍ، يجب أن يبدأ workflow **"Crypto News Bot"** تلقائياً.

---

## 🔍 تحقق من النجاح

```bash
# على جهازك المحلي، فحص آخر تشغيل للـ workflows
gh run list --workflow=trigger-bot.yml --limit=5
gh run list --workflow=news.yml --limit=5
```

يجب أن ترى تشغيلات بالحالة `success`.

---

## 🧰 بدائل cron-job.org (لو احتجت)

لو ما تريد استعمال cron-job.org، بدائل مجانية مماثلة:

| الخدمة | المميزات | العيب |
|---|---|---|
| **[cron-job.org](https://cron-job.org)** | مجاني تماماً، واجهة بسيطة، notifications | يحتاج تسجيل |
| **[UptimeRobot](https://uptimerobot.com)** | مجاني، يراقب الـ uptime أيضاً | يحتاج API integration |
| **[EasyCron](https://www.easycron.com)** | مجاني محدود (100 cron job) | واجهة أقدم |
| **GitHub Actions على ريبو آخر** | مجاني تماماً داخل GitHub | يحتاج ريبو ثاني + PAT |
| **Cloudflare Workers** | مجاني تماماً، serverless | يحتاج كتابة JS code |
| **Vercel Cron** | مجاني للـ hobby tier | يحتاج حساب Vercel |

**الأنسب للمبتدئ**: cron-job.org (لهذا اخترناه في هذا الدليل).

---

## ⚠️ مشاكل شائعة وحلولها

### المشكلة: `401 Unauthorized`
- **السبب**: PAT خاطئ أو منتهي.
- **الحل**: أعد إنشاء PAT وتحديث الـ header على cron-job.org.

### المشكلة: `404 Not Found`
- **السبب**: المسار في الـ URL خاطئ.
- **الحل**: تأكد أن `USER/REPO` صحيح وأن `trigger-bot.yml` موجود فعلاً على الفرع الافتراضي.

### المشكلة: `422 Unprocessable Entity`
- **السبب**: `ref` في الـ body غير صحيح.
- **الحل**: غيّر `"main"` لـ `"master"` لو فرعك الافتراضي هو master.

### المشكلة: `403 Resource not accessible by token`
- **السبب**: PAT لا يملك صلاحية `workflow`.
- **الحل**: أعد إنشاء PAT مع تفعيل scope `workflow`.

### المشكلة: الـ workflow لا يبدأ على GitHub رغم 200 OK
- **السبب 1**: الـ workflow معطّل (زر "Enable workflow" ظاهر على صفحة Actions).
- **السبب 2**: `news.yml` على فرع مختلف عن `trigger-bot.yml`.
- **الحل**: فعّل الـ workflow + تأكد أن كل ملفات `.github/workflows/*.yml` على نفس الفرع الافتراضي.

### المشكلة: cron-job.org يفشل باستمرار
- **السبب**: أحياناً cron-job.org يحجب HEAD requests لـ api.github.com.
- **الحل**: غيّر الـ Request Method لـ POST (افتراضياً قد يكون GET في بعض الإصدارات).

---

## 📞 اختبار سريع من terminal

قبل إعداد cron-job.org، اختبر الـ API يدوياً:

```bash
curl -X POST \
  -H "Authorization: Bearer ghp_XXX" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/USER/REPO/actions/workflows/trigger-bot.yml/dispatches \
  -d '{"ref":"main"}'
```

- لو رجع `204 No Content` → نجح ✅
- لو رجع `401` أو `404` → راجع المشاكل أعلاه.

---

## ✅ Checklist نهائي

- [ ] PAT أنشئ بصلاحية `workflow`
- [ ] `trigger-bot.yml` مرفوع على الفرع الافتراضي
- [ ] `news.yml` على نفس الفرع
- [ ] حساب cron-job.org أُنشئ
- [ ] Cron job جديد بـ:
  - URL: `https://api.github.com/repos/USER/REPO/actions/workflows/trigger-bot.yml/dispatches`
  - Method: POST
  - Headers: `Authorization: Bearer ghp_xxx`, `Accept`, `Content-Type`
  - Body: `{"ref":"main"}`
  - Schedule: daily
- [ ] اختبار "Run now" ناجح
- [ ] ظهور workflow run جديد على GitHub Actions
- [ ] (اختياري) تفعيل notifications على cron-job.org

لو كل شيء أعلاه ✅ → البوت مضمون أنه يستيقظ يومياً مهما حصل.
