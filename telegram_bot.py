import os, time, json, re, threading, logging
from datetime import datetime
import requests
from flask import Flask, jsonify, request

from config import (
    log, tz, TOKEN, CHAT_ID, RENDER_URL, CHANNEL_LINK, CHANNEL_NAME, CHANNEL_ID,
    SEND_TO_CHANNEL, NEWS_SOURCES, HEADERS,
    _cache, _started, last_id, _user_state,
    bot_shutdown, channel_enabled, auto_alerts_enabled, alert_categories,
    daily_summary_enabled, bot_resume_time, _skip_old_news_once,
    ALERT_COOLDOWN, last_alerts_hashes, sent_news_hashes,
    ALLOWED_USERS, SETTINGS_FILE,
    load_settings, save_settings, is_channel_enabled,
    is_owner, is_allowed, add_user, remove_user,
    save_sent_news,
)
from filters import (
    classify_news, get_coin_keywords, time_ago, is_category_allowed,
    CRYPTO_CONTEXT_KEYWORDS, REJECTION_KEYWORDS,
    AR_CRITICAL_KEYWORDS, AR_REJECTION_KEYWORDS,
)
from rss import (
    get_all_news, deduplicate_news, news_hash, clean_html,
    extract_summary, extract_image_from_html, _strip_source_from_title,
    parse_rss_source,
)
from translate import (
    translate_to_arabic, translate_news_item,
    translate_source_name, translate_coin_name,
)


# ═══════════════════════════════════════════════════════════
# تنسيق وبناء الأخبار
# ═══════════════════════════════════════════════════════════
def fmt_news_item(item, show_summary=True, translate=True, show_header=True):
    """🆕 تنسيق جديد مبسط:
    🔵 [العنوان المترجم مع إيموجي العملات 💰]
    ✉️
    """
    title = item.get("title", "")
    title_ar = item.get("title_ar", "")
    summary = item.get("summary", "")
    summary_ar = item.get("summary_ar", "")
    link = item.get("link", "")
    image_url = item.get("image", "")
    source = item.get("source", "")
    timestamp = item.get("timestamp", 0)
    categories = classify_news(item)
    # ترجمة العنوان للعربية
    if translate and title and not title_ar:
        title_ar = translate_to_arabic(title)
        item["title_ar"] = title_ar
    if translate and summary and not summary_ar:
        summary_ar = translate_to_arabic(summary)
        item["summary_ar"] = summary_ar
    # العنوان النهائي - 🆕🆕 إجبار الترجمة بالعربية (لا نستخدم النص الإنجليزي أبداً)
    # لو فشلت كل الطرق (Gemini + Google) → نُرجع None → البوت يتخطى الخبر
    if (not title_ar or title_ar == title) and translate and title:
        title_ar = translate_to_arabic(title, force=True)
    # 🆕 لو الترجمة فشلت تماماً، نرجع None للبوت فيتخطى الخبر
    if not title_ar or title_ar == title:
        return None  # 🚫 تخطي الخبر (لا إرسال رسالة خطأ)
    final_title = title_ar

    # 🚫 تم حذف نظام إيموجي العملات - كان يسبب أخطاء كارثية
    # (يطابق "sol" في "Solomon"، "tron" في "Patron"، "link" في "LinkedIn")

    # البناء بالشكل الجديد المبسط
    msg = ""
    msg += f"🔵 {final_title}\n"

    # إضافة الملخص إن وُجد (مترجم للعربية)
    if show_summary:
        if summary_ar and translate:
            clean_summary = summary_ar.strip()
            # 🆕 إزالة أي نقاط معلقة في النهاية (من قص الكلمات)
            clean_summary = clean_summary.rstrip("…")
            clean_summary = clean_summary.rstrip(" ")
            # 🆕🆕 لا نقص - نعرض الملخص كاملاً (Gemini يكتبه مختصراً)
            # فقط لو كان طويلاً جداً (> 800 حرف)، نقص عند آخر نقطة كاملة
            if len(clean_summary) > 800:
                cut_at = clean_summary[:800].rfind(".")
                if cut_at > 200:
                    clean_summary = clean_summary[:cut_at + 1]
                else:
                    # لو ما فيش نقطة، نقص عند آخر مسافة
                    cut_at = clean_summary[:800].rfind(" ")
                    if cut_at > 200:
                        clean_summary = clean_summary[:cut_at] + "..."
                    else:
                        clean_summary = clean_summary[:800] + "..."
            if clean_summary:
                msg += f"\n{clean_summary}\n"
        elif summary:
            translated_summary = translate_to_arabic(summary[:1500])
            if translated_summary and translated_summary != summary:
                clean_summary = translated_summary.strip()
                clean_summary = clean_summary.rstrip("…")
                clean_summary = clean_summary.rstrip(" ")
                if len(clean_summary) > 800:
                    cut_at = clean_summary[:800].rfind(".")
                    if cut_at > 200:
                        clean_summary = clean_summary[:cut_at + 1]
                    else:
                        cut_at = clean_summary[:800].rfind(" ")
                        if cut_at > 200:
                            clean_summary = clean_summary[:cut_at] + "..."
                        else:
                            clean_summary = clean_summary[:800] + "..."
                if clean_summary:
                    msg += f"\n{clean_summary}\n"

    # 🚫 تم حذف رابط المصدر بناءً على طلب المستخدم

    # ✉️ في النهاية
    msg += "\n✉️\n"

    return msg


def build_latest_news(limit=10):
    """📰 آخر الأخبار"""
    news = get_all_news()
    if not news:
        return "⚠️ تعذّر جلب الأخبار. حاول لاحقاً."
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    msg = ""
    for item in news[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg


def build_breaking_news(limit=5):
    """🔥 أخبار عاجلة"""
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    breaking = [n for n in news if "breaking" in classify_news(n) or "hack" in classify_news(n)]
    if not breaking:
        return "✅ <b>لا توجد أخبار عاجلة حالياً</b>\n\nالسوق هادئ نسبياً."
    msg = ""
    for item in breaking[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=True, translate=True, show_header=False)
        msg += "\n"
    return msg


def build_macro_news(limit=8):
    """🇺🇸 اقتصاد كلي"""
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    macro = [n for n in news if n.get("category") == "fed" or
             "fed" in classify_news(n)]
    if not macro:
        return "ℹ️ لا توجد أخبار اقتصادية حديثة."
    msg = ""
    for item in macro[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg


def build_coin_news(symbol, limit=5):
    """💎 أخبار عملة معينة"""
    symbol = symbol.upper().strip()
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    coin_news = []
    for n in news:
        coins = get_coin_keywords(f"{n.get('title', '')} {n.get('summary', '')}")
        if symbol in coins:
            coin_news.append(n)
    if not coin_news:
        return f"ℹ️ لا توجد أخبار حديثة عن <b>{symbol}</b>"
    msg = ""
    for item in coin_news[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg


# ═══════════════════════════════════════════════════════════
# التنبيهات التلقائية
# ═══════════════════════════════════════════════════════════
def scan_news_loop():
    """يفحص الأخبار الجديدة ويرسل تنبيهات للأخبار المهمة (عاجل/اختراق/تقني/سوقي)
    🔧 إصلاحات:
    - احترام alert_categories
    - تطبيق ALERT_COOLDOWN
    - استخدام deduplicate_news قبل الفلترة
    - منع التكرار عبر المصادر
    - 🆕 احترام bot_shutdown
    - 🔧 إصلاح: قراءة channel_enabled مباشرة من globals في كل دورة
    - 🆕 منع إرسال الأخبار القديمة المتراكمة أثناء فترة الإيقاف
    """
    global bot_shutdown, channel_enabled, auto_alerts_enabled, alert_categories
    global bot_resume_time, _skip_old_news_once
    time.sleep(20)
    while True:
        try:
            # 🆕 احترام الإيقاف الكامل للبوت
            if bot_shutdown:
                log.info("🔇 Bot is shutdown — skipping news scan")
                time.sleep(300)
                continue
            if not auto_alerts_enabled:
                time.sleep(300)
                continue
            # 🔧 إصلاح: إعادة تحميل الإعدادات من Gist/محلي في كل دورة
            # هذا يضمن أن أي تغيير في channel_enabled يُقرأ حتى لو لم يُرَ من thread آخر
            load_settings()
            log.info(f"📊 Settings: channel_enabled={channel_enabled}, bot_shutdown={bot_shutdown}")
            # 🆕 فحص: هل نحن في أول دورة بعد استئناف البوت؟
            # إذا نعم، نضيف كل الأخبار الحالية (القديمة) لـ sent_news_hashes دون إرسال
            if bot_resume_time > 0 and not _skip_old_news_once:
                log.info(f"🔄 First scan after resume at {datetime.fromtimestamp(bot_resume_time, tz=tz).strftime('%H:%M:%S')} — marking old news as sent")
                # مسح الكاش للحصول على أخبار طازجة
                if "all_news" in _cache:
                    del _cache["all_news"]
                old_news = get_all_news()
                old_news = deduplicate_news(old_news)
                skipped_count = 0
                for item in old_news:
                    item_ts = item.get("timestamp", 0)
                    # الأخبار الأقدم من وقت الاستئناف = قديمة، تجاوزها
                    if item_ts > 0 and item_ts < bot_resume_time:
                        h = news_hash(item)
                        if h not in sent_news_hashes:
                            sent_news_hashes.add(h)
                            skipped_count += 1
                if skipped_count > 0:
                    save_sent_news()
                    log.info(f"⏭️ Skipped {skipped_count} old news items (accumulated during shutdown)")
                _skip_old_news_once = True
                # إعادة ضبط bot_resume_time بعد المعالجة
                bot_resume_time = 0
                save_settings()
                time.sleep(60)  # انتظر دقيقة قبل بدء الفحص الحقيقي
                continue
            log.info("🔍 Scanning news for important alerts...")
            # مسح الكاش للحصول على أخبار طازجة
            if "all_news" in _cache:
                del _cache["all_news"]
            news = get_all_news()
            if not news:
                time.sleep(300)
                continue
            # 🔧 إصلاح: إزالة المكرر قبل الفلترة
            news = deduplicate_news(news)
            now = time.time()
            alerts_sent = 0
            # 🆕 سجل تشخيصي: كم خبراً متاحاً وكم مستوفياً للشروط
            total_news = len(news)
            important_news = 0
            already_sent = 0
            old_news_skipped = 0
            # نفحص آخر 40 خبر
            for item in news[:40]:
                # 🆕 فحص إضافي: تجاوز الأخبار القديمة (timestamp < 30 دقيقة)
                # هذا يمنع إرسال أخبار قديمة جداً حتى لو لم تكن في sent_news_hashes
                item_ts = item.get("timestamp", 0)
                if item_ts > 0 and (now - item_ts) > 10800:  # 3 ساعات
                    old_news_skipped += 1
                    # أضفها لـ sent_news_hashes حتى لا تُفحص مرة أخرى
                    h_old = news_hash(item)
                    if h_old not in sent_news_hashes:
                        sent_news_hashes.add(h_old)
                        save_sent_news()
                    continue
                categories = classify_news(item)
                # 🚫 تم حذف matched_cats - كان يقبل أخبار جيوسياسة وأسهم وحروب
                # الفلتر الجديد: فقط كريبتو + فيدرالي + وارش
                # 🚨 فلتر صارم جداً: فقط الأحداث المحددة
                # 1) اختراق/سرقة  2) انهيار/تصحيح حاد  3) سيولة مؤسسية كبيرة
                # 4) تحديث برمجي  5) فك توكن  6) حرق توكن  7) قرارات الفائدة
                news_text = (item.get("title", "") + " " + item.get("summary", "")).lower()

                # 🆕🆕 مسار خاص للأخبار العربية (تتخطى الفلترة الإنجليزية)
                # الأخبار العربية أصلية ولا تحتاج ترجمة، فلترتها مختلفة
                source_lang = ""
                for src_name, src_info in NEWS_SOURCES.items():
                    if src_name == item.get("source", ""):
                        source_lang = src_info.get("lang", "en")
                        break

                if source_lang == "ar":
                    # فلترة عربية صارمة - فقط الأحداث المهمة
                    has_ar_critical = any(kw in news_text for kw in AR_CRITICAL_KEYWORDS)
                    has_ar_rejection = any(kw in news_text for kw in AR_REJECTION_KEYWORDS)
                    if not has_ar_critical or has_ar_rejection:
                        continue
                    # ✅ خبر عربي مهم - تم القبول (بدون حاجة للترجمة)
                    important_news += 1
                    # 🚫 تم حذف allowed_cats/matched_cats - لا حاجة لها في الفلتر الجديد
                    h = news_hash(item)
                    if h in sent_news_hashes:
                        already_sent += 1
                        continue
                    sent_news_hashes.add(h)
                    save_sent_news()
                    last_alerts_hashes[h] = now
                    # ⚠️ تخطي الترجمة للخبر العربي (عربي أصلي)
                    item["title_ar"] = item.get("title", "")
                    item["summary_ar"] = item.get("summary", "")
                    msg = fmt_news_item(item, show_summary=True, translate=False)
                    image_url = item.get("image", "")
                    broadcast_alert(msg, image_url)
                    alerts_sent += 1
                    print(f"  ✉️ [AR] {item.get('title', '')[:60]}...")
                    time.sleep(1.5)
                    continue

                # (1) سياق الكريبتو إجباري
                has_crypto_context = any(kw in news_text for kw in CRYPTO_CONTEXT_KEYWORDS)

                # ✅ القبول: سياق كريبتو كافي (مطابق لمنطق GA mode)
                if not has_crypto_context:
                    continue

                # (3) كلمات ترفض الخبر (سبام وتحليلات فقط — لا حروب/أسهم عريضة)
                has_rejection = any(kw in news_text for kw in REJECTION_KEYWORDS)
                if has_rejection:
                    continue
                # 🚫 رفض إضافي: أي مصدر Reddit (احتياط)
                if "reddit" in (item.get("source", "") or "").lower():
                    continue

                important_news += 1
                # 🔧 إصلاح: احترام alert_categories - إن كانت كل الفئات المطابقة معطّلة، تخطّي
                # 🚫 تم حذف allowed_cats - الفلتر الجديد لا يستخدم matched_cats
                h = news_hash(item)
                # 🆕 ذاكرة دائمة: إذا الخبر أُرسل من قبل، لا تعد إرساله أبداً
                if h in sent_news_hashes:
                    already_sent += 1
                    continue
                # 🔧 إصلاح: تطبيق ALERT_COOLDOWN - فحص آخر تنبيه
                if h in last_alerts_hashes:
                    last_time = last_alerts_hashes[h]
                    if now - last_time < ALERT_COOLDOWN:
                        continue
                # تحديث الذاكرة الدائمة + cooldown
                sent_news_hashes.add(h)
                save_sent_news()
                last_alerts_hashes[h] = now
                # ترجمة الخبر قبل الإرسال
                translate_news_item(item)
                # إرسال للجميع - التنسيق المبسط
                msg = fmt_news_item(item, show_summary=True, translate=True)
                # 🆕🆕 لو fmt_news_item رجع None، معناه الترجمة فشلت → تخطي الخبر
                if not msg:
                    log.info(f"   ⏭️ Skipping news (translation failed): {item.get('title', '')[:60]}")
                    continue
                image_url = item.get("image", "")
                broadcast_alert(msg, image_url)
                alerts_sent += 1
            # 🆕 سجل تشخيصي شامل
            log.info(f"📊 News scan: total={total_news}, important={important_news}, already_sent={already_sent}, old_skipped={old_news_skipped}, alerts_sent={alerts_sent}, sent_hashes={len(sent_news_hashes)}")
            # 🆕 تحديث الإحصائيات اليومية
            try:
                # جمع فئات الأخبار المهمة في هذه الدورة
                cats_today = []
                for item in news[:40]:
                    if item.get("timestamp", 0) > 0:
                        cats_today.extend(classify_news(item))
                update_daily_stats(alerts_sent=alerts_sent, important=important_news, total=total_news, categories=cats_today)
            except Exception:
                pass
            if alerts_sent > 0:
                log.info(f"🔔 Sent {alerts_sent} news alerts")
            elif important_news > 0:
                log.info(f"ℹ️ Found {important_news} important news but all already sent or in cooldown")
            else:
                log.info("ℹ️ No important news found in this scan")
            # 🔧 إصلاح: حفظ مجمّع إجباري في نهاية كل دورة
            save_sent_news(force=True)
            # 🔧 إصلاح: تنظيف last_alerts_hashes من المدخلات القديمة (>24 ساعة)
            old_hashes = [h for h, t in last_alerts_hashes.items() if now - t > 86400]
            for h in old_hashes:
                del last_alerts_hashes[h]
            time.sleep(300)  # كل 5 دقائق
        except Exception as e:
            log.warning(f"scan_news_loop err: {e}")
            time.sleep(60)


# ═══════════════════════════════════════════════════════════
# إرسال الرسائل
# ═══════════════════════════════════════════════════════════
def send_telegram(chat_id, msg, image_url=None):
    """🆕 إرسال موحد: sendPhoto إذا توفرت صورة، sendMessage إذا لا
    🔧 إصلاح: معالجة أفضل لأخطاء sendPhoto + سجل سبب الفشل
    🆕🆕 إضافة شعار القناة newscrypto1m@ على الصور
    """
    if not TOKEN or not chat_id:
        return False
    try:
        if image_url and image_url.startswith("http"):
            # 🆕 إرسال كصورة مع تعليق
            # 🔧 إصلاح: التحقق من صحة الرابط وتنظيفه
            clean_url = image_url.replace("&amp;", "&").strip()
            # تجاهل الروابط التي قد تكون غير صالحة (مثلاً تحتوي مسافات)
            if " " in clean_url or len(clean_url) > 2000:
                log.warning(f"sendPhoto skipped: invalid URL length or format")
            else:
                # 🆕🆕 محاولة تحميل الصورة وإضافة الشعار عليها
                watermarked_image = _add_watermark_to_image(clean_url)
                if watermarked_image:
                    # إرسال الصورة المعدّلة كملف (multipart/form-data)
                    p_data = {
                        "chat_id": chat_id,
                        "caption": msg[:1024],
                        "parse_mode": "HTML"
                    }
                    files = {"photo": ("image.jpg", watermarked_image, "image/jpeg")}
                    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                      data=p_data, files=files, timeout=30)
                    if r.status_code == 200:
                        try:
                            if r.json().get("ok"):
                                return True
                            else:
                                err_desc = r.json().get("description", "unknown")
                                log.warning(f"sendPhoto API error: {err_desc}")
                        except Exception:
                            pass
                    else:
                        log.warning(f"sendPhoto HTTP {r.status_code}")
                else:
                    # fallback: إرسال الرابط مباشرة (بدون شعار)
                    p = {"chat_id": chat_id, "photo": clean_url, "caption": msg[:1024],
                         "parse_mode": "HTML"}
                    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                      json=p, timeout=20)
                    if r.status_code == 200:
                        try:
                            if r.json().get("ok"):
                                return True
                            else:
                                err_desc = r.json().get("description", "unknown")
                                log.warning(f"sendPhoto API error: {err_desc}")
                        except Exception:
                            pass
                    else:
                        log.warning(f"sendPhoto HTTP {r.status_code}")
        # لو فشل sendPhoto (مثلاً رابط غير صالح)، نرسل كنص
        # 🔧 إصلاح: تفعيل web preview ليعرض الصورة تلقائياً إن أمكن
        p = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML",
             "disable_web_page_preview": False}
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json=p, timeout=15)
        return True
    except Exception as e:
        log.warning(f"send_telegram err: {e}")
        return False


def _add_watermark_to_image(image_url):
    """🆕🆕 يحمل الصورة من URL ويضيف شعار القناة newscrypto1m@ عليها
    يعيد الصورة كـ bytes (JPEG) جاهزة للإرسال
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        # تحميل الصورة من URL
        r = requests.get(image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None

        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        width, height = img.size

        # محاولة تحميل خط عربي (إن وُجد) أو خط افتراضي
        try:
            # ابحث عن خط في النظام
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            ]
            font = None
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, max(20, width // 25))
                    break
                except:
                    continue
            if not font:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()

        # إنشاء طبقة شفافة للشعار
        draw = ImageDraw.Draw(img)
        watermark_text = "@newscrypto1m"

        # حساب حجم النص
        try:
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except:
            text_width, text_height = 200, 30

        # موقع الشعار: أسفل اليمين مع padding
        padding = 15
        x = width - text_width - padding - 10
        y = height - text_height - padding - 10

        # خلفية شبه شفافة خلف النص (للوضوح)
        bg_padding = 8
        draw.rectangle(
            [x - bg_padding, y - bg_padding,
             x + text_width + bg_padding, y + text_height + bg_padding],
            fill=(0, 0, 0, 180)
        )

        # النص بالأبيض
        draw.text((x, y), watermark_text, fill=(255, 255, 255), font=font)

        # حفظ كـ bytes
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85)
        return output.getvalue()

    except Exception as e:
        log.warning(f"watermark err: {e}")
        return None


def send_msg(msg, kb=None, cid=None):
    """إرسال رسالة عادية (للمالك أو مستخدم محدد)
    🔧 إصلاح: تسجيل الأخطاء بدلاً من إخفائها
    """
    t = cid or CHAT_ID
    if not t or not TOKEN:
        return
    try:
        p = {"chat_id": t, "text": msg, "parse_mode": "HTML",
             "disable_web_page_preview": True}
        if kb:
            p["reply_markup"] = json.dumps(kb) if isinstance(kb, dict) else kb
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json=p, timeout=15)
    except Exception as e:
        log.warning(f"send_msg err: {e}")


def send_to_channel(msg, image_url=None):
    """🆕 إرسال رسالة إلى القناة العامة (مع صورة إن وُجدت)
    🔧 إصلاح: فحص مزدوج + سجل عند الحظر
    """
    if not TOKEN or not CHANNEL_ID:
        log.info("📢 send_to_channel: BLOCKED (no TOKEN or CHANNEL_ID)")
        return False
    if not is_channel_enabled():
        log.info("📢 send_to_channel: BLOCKED by is_channel_enabled()=False")
        return False
    result = send_telegram(CHANNEL_ID, msg, image_url)
    if result:
        log.info(f"📢 Sent to channel {CHANNEL_ID}")
    return result


def broadcast_alert(msg, image_url=None):
    """🆕 إرسال التنبيه لكل المستخدمين + القناة (مع صورة إن وُجدت)
    🔧 إصلاح: احترام is_channel_enabled() و bot_shutdown + سجلات تشخيص
    """
    global bot_shutdown, channel_enabled
    # 🆕 احترام إيقاف البوت الكامل
    if bot_shutdown:
        log.info("🔇 Bot is shutdown — skipping broadcast")
        return
    # 🔧 إصلاح: فحص صريح قبل الإرسال للقناة
    channel_ok = is_channel_enabled()
    log.info(f"📡 broadcast_alert: channel_ok={channel_ok}, channel_enabled={channel_enabled}")
    if channel_ok:
        send_to_channel(msg, image_url)
    else:
        log.info("📡 broadcast_alert: SKIPPED channel (disabled by owner)")
    # إرسال للمستخدمين الخاصين
    if not TOKEN or not ALLOWED_USERS:
        send_msg(msg)
        return
    sent = 0
    for uid in ALLOWED_USERS:
        try:
            send_telegram(uid, msg, image_url)
            sent += 1
        except Exception:
            pass
    log.info(f"📡 Broadcast sent to {sent}/{len(ALLOWED_USERS)} users")


# ═══════════════════════════════════════════════════════════
# لوحات المفاتيح
# ═══════════════════════════════════════════════════════════
def main_kb():
    return {"keyboard": [
        [{"text": "📰 آخر الأخبار"}, {"text": "🔥 أخبار عاجلة"}],
        [{"text": "💎 أخبار عملتي"}, {"text": "🇺🇸 اقتصاد كلي"}],
        [{"text": "⚙️ الإعدادات"}]
    ], "resize_keyboard": True, "is_persistent": True}


# ═══════════════════════════════════════════════════════════
# معالجة التحديثات
# ═══════════════════════════════════════════════════════════
def handle_update(u):
    m = u.get("message", {})
    if m:
        chat = m.get("chat", {})
        cid = chat.get("id")
        txt = m.get("text", "").strip()
        if cid and txt:
            handle_msg(cid, txt, chat)
        return
    cb = u.get("callback_query", {})
    if cb:
        cid = cb.get("message", {}).get("chat", {}).get("id")
        d = cb.get("data", "")
        cb_id = cb.get("id", "")
        if cid and d:
            handle_cb(cid, d, cb_id)


def handle_msg(cid, txt, chat=None):
    # 🆕 احترام الإيقاف الكامل للبوت (فقط المالك يمكنه استخدام البوت)
    if bot_shutdown and not is_owner(cid):
        # رد مرة واحدة فقط برسالة الإيقاف (لتفادي الإزعاج)
        if txt == "/start":
            send_msg("🔇 <b>البوت متوقف حالياً للصيانة.</b>\n\nيرجى المحاولة لاحقاً.", None, cid)
        return
    # 🛡️ أوامر المالك فقط
    if is_owner(cid):
        if txt.startswith("/add "):
            target = txt.replace("/add ", "").strip().replace(" ", "")
            if target.isdigit():
                if add_user(target):
                    send_msg(f"✅ <b>تمت إضافة المستخدم</b>\n🆔 <code>{target}</code>\n\nالعدد الإجمالي: {len(ALLOWED_USERS)}", main_kb(), cid)
                else:
                    send_msg(f"ℹ️ المستخدم <code>{target}</code> موجود مسبقاً.", main_kb(), cid)
            else:
                send_msg("❌ الصيغة خاطئة.\n\nمثال: <code>/add 123456789</code>", main_kb(), cid)
            return
        if txt.startswith("/remove "):
            target = txt.replace("/remove ", "").strip().replace(" ", "")
            if target.isdigit():
                if remove_user(target):
                    send_msg(f"✅ <b>تم حذف المستخدم</b>\n🆔 <code>{target}</code>\n\nالعدد الإجمالي: {len(ALLOWED_USERS)}", main_kb(), cid)
                else:
                    send_msg(f"❌ لا يمكن حذف <code>{target}</code>.", main_kb(), cid)
            else:
                send_msg("❌ الصيغة خاطئة.\n\nمثال: <code>/remove 123456789</code>", main_kb(), cid)
            return
        if txt == "/users":
            msg = f"👥 <b>القائمة البيضاء</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += f"📊 العدد الإجمالي: {len(ALLOWED_USERS)} مستخدم\n\n"
            for i, uid in enumerate(sorted(ALLOWED_USERS), 1):
                owner_tag = " 👑" if uid == int(CHAT_ID) else ""
                msg += f"{i}. <code>{uid}</code>{owner_tag}\n"
            msg += "\n💡 للإضافة: <code>/add ID</code>\n💡 للحذف: <code>/remove ID</code>"
            send_msg(msg, main_kb(), cid)
            return

    # 🔒 فحص القائمة البيضاء
    if not is_allowed(cid):
        if txt == "/start":
            send_msg("🔒 هذا البوت خاص.\n\nتواصل مع المالك للوصول.", None, cid)
            log.warning(f"⛔ Access denied for chat_id: {cid}")
            if chat and CHAT_ID:
                first_name = chat.get("first_name", "غير معروف")
                username = chat.get("username", "")
                notify = f"🔔 <b>محاولة دخول جديدة</b>\n"
                notify += "━━━━━━━━━━━━━━━━━━\n\n"
                notify += f"👤 الاسم: {first_name}\n"
                if username:
                    notify += f"📎 المعرف: @{username}\n"
                notify += f"🆔 Chat ID: <code>{cid}</code>\n\n"
                notify += f"لإضافته أرسل: <code>/add {cid}</code>"
                send_msg(notify)
        return

    # حالة انتظار إدخال عملة
    if _user_state.get(cid) == "waiting_for_symbol":
        _user_state[cid] = None
        send_msg("⏳ جاري البحث...", cid=cid)
        send_msg(build_coin_news(txt), main_kb(), cid)
        return

    if txt == "/start":
        if is_owner(cid):
            msg = "📰 <b>بوت الأخبار الكريبتو</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📡 المصادر: CoinDesk, Cointelegraph, Decrypt, Fed, Crypto.News\n"
            msg += f"🔔 التنبيهات: {'🟢 مفعّل' if auto_alerts_enabled else '🔴 معطّل'}\n"
            msg += f"👥 المستخدمون: {len(ALLOWED_USERS)}\n"
            # 🔧 إصلاح: استخدام CHANNEL_LINK و CHANNEL_NAME بدلاً من كونها ميتة
            if CHANNEL_LINK:
                msg += f"📢 القناة: <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>\n"
            msg += "\nاختر من القائمة بالأسفل:"
            send_msg(msg, main_kb(), cid)
        else:
            first_name = chat.get("first_name", "") if chat else ""
            msg = f"📰 <b>أهلاً {first_name}!</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📊 <b>بوت الأخبار الكريبتو والاقتصادية</b>\n"
            msg += "📡 مصادر موثوقة متعددة\n\n"
            msg += "✅ <b>تم تفعيل استقبال الأخبار</b>\n"
            msg += "⏳ سيصلك تنبيه فور ظهور خبر عاجل\n\n"
            # 🔧 إصلاح: عرض رابط القناة العامة للمستخدمين العاديين
            if CHANNEL_LINK:
                msg += f"📢 انضم لقناتنا: <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>\n\n"
            msg += "💡 <i>أنت مستلم للأخبار فقط.</i>"
            send_msg(msg, None, cid)
    elif txt == "📰 آخر الأخبار":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_latest_news(10), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "🔥 أخبار عاجلة":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_breaking_news(5), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "💎 أخبار عملتي":
        if is_owner(cid):
            _user_state[cid] = "waiting_for_symbol"
            msg = "💎 <b>أخبار عملة معينة</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📝 أرسل رمز العملة:\n"
            msg += "مثال: <code>BTC</code> أو <code>ETH</code> أو <code>SOL</code>"
            send_msg(msg, None, cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "🇺🇸 اقتصاد كلي":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_macro_news(8), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "⚙️ الإعدادات":
        if is_owner(cid):
            show_settings(cid)
        else:
            send_msg("ℹ️ الإعدادات متاحة للمالك فقط.", None, cid)
    else:
        if is_owner(cid):
            send_msg("استخدم القائمة بالأسفل", main_kb(), cid)
        else:
            send_msg("ℹ️ أنت مستلم للأخبار فقط. انتظر التنبيهات التلقائية.", None, cid)


def show_settings(cid):
    """عرض إعدادات التنبيهات
    🔧 إصلاح: عرض الفئات الحقيقية المحترمة + إضافة أزرار تبديل
    🆕 إضافة زر تبديل الإرسال للقناة + زر إيقاف البوت الكامل (للمالك فقط)
    """
    status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
    shutdown_status = "🔴 متوقف" if bot_shutdown else "🟢 يعمل"
    channel_status = "🟢 مفعّل" if is_channel_enabled() else "🔴 معطّل"
    msg = "⚙️ <b>إعدادات التنبيهات</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🔔 <b>التنبيهات:</b> {status}\n"
    msg += f"🔇 <b>حالة البوت:</b> {shutdown_status}\n"
    msg += f"📢 <b>القناة العامة:</b> {channel_status}\n"
    if CHANNEL_ID:
        msg += f"   ┗ المعرف: <code>{CHANNEL_ID}</code>\n"
    msg += f"⏰ <b>الفحص كل:</b> 5 دقائق\n"
    msg += f"🔒 <b>Cooldown:</b> 6 ساعات لكل خبر\n\n"
    msg += "📊 <b>فئات التنبيه (محترمة فعلياً):</b>\n"
    msg += f"  🚨 أخبار عاجلة: {'🟢' if alert_categories.get('breaking', True) else '🔴'}\n"
    msg += f"  📰 كريبتو (ETF/حيتان): {'🟢' if alert_categories.get('crypto', True) else '🔴'}\n"
    msg += f"  🇺🇸 اقتصاد كلي (Fed): {'🟢' if alert_categories.get('macro', True) else '🔴'}\n"
    msg += f"  🔧 تقني: {'🟢' if alert_categories.get('tech', True) else '🔴'}\n"
    msg += f"  📈 سوقي: {'🟢' if alert_categories.get('market', True) else '🔴'}\n"

    # بناء لوحة المفاتيح
    kb_buttons = [
        [{"text": f"{'🔴 إيقاف' if auto_alerts_enabled else '🟢 تفعيل'} التنبيهات", "callback_data": "toggle_alerts"}],
        [
            {"text": f"{'🟢' if alert_categories.get('breaking', True) else '🔴'} عاجل", "callback_data": "toggle_breaking"},
            {"text": f"{'🟢' if alert_categories.get('crypto', True) else '🔴'} كريبتو", "callback_data": "toggle_crypto"},
        ],
        [
            {"text": f"{'🟢' if alert_categories.get('macro', True) else '🔴'} اقتصاد", "callback_data": "toggle_macro"},
            {"text": f"{'🟢' if alert_categories.get('tech', True) else '🔴'} تقني", "callback_data": "toggle_tech"},
        ],
        [
            {"text": f"{'🟢' if alert_categories.get('market', True) else '🔴'} سوقي", "callback_data": "toggle_market"},
        ],
        # 🆕 زر تبديل الإرسال للقناة (يظهر فقط إذا كان CHANNEL_ID مضبوطاً)
    ]
    if CHANNEL_ID:
        kb_buttons.append([
            {"text": f"{'🔴 إيقاف' if is_channel_enabled() else '🟢 تفعيل'} الإرسال للقناة",
             "callback_data": "toggle_channel"}
        ])
    # 🆕 زر تبديل الملخص اليومي
    kb_buttons.append([
        {"text": f"{'🔴 إيقاف' if daily_summary_enabled else '🟢 تفعيل'} الملخص اليومي",
         "callback_data": "toggle_summary"}
    ])
    # 🆕 زر إيقاف/تشغيل البوت الكامل (المالك فقط)
    if is_owner(cid):
        if bot_shutdown:
            kb_buttons.append([
                {"text": "🟢 تشغيل البوت (إلغاء الإيقاف)", "callback_data": "toggle_shutdown"}
            ])
        else:
            kb_buttons.append([
                {"text": "🔴 إيقاف البوت نهائياً (المالك فقط)", "callback_data": "toggle_shutdown"}
            ])
    kb_buttons.append([{"text": "✅ تم", "callback_data": "done_settings"}])
    kb = {"inline_keyboard": kb_buttons}
    send_msg(msg, kb, cid)


def handle_cb(cid, d, cb_id):
    global auto_alerts_enabled, channel_enabled, bot_shutdown, bot_resume_time, _skip_old_news_once, daily_summary_enabled
    if not is_allowed(cid):
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                          json={"callback_query_id": cb_id, "text": "🔒 مرفوض"}, timeout=10)
        except Exception as e:
            log.warning(f"answerCallbackQuery err: {e}")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                      json={"callback_query_id": cb_id, "text": "✅"}, timeout=10)
    except Exception as e:
        log.warning(f"answerCallbackQuery err: {e}")
    # 🔧 إصلاح: تبديل الفئات الفردية فعلياً
    category_toggles = {
        "toggle_breaking": "breaking",
        "toggle_crypto": "crypto",
        "toggle_macro": "macro",
        "toggle_tech": "tech",
        "toggle_market": "market",
    }
    if d == "toggle_alerts":
        auto_alerts_enabled = not auto_alerts_enabled
        save_settings()
        status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
        send_msg(f"✅ التنبيهات: <b>{status}</b>", main_kb(), cid)
    elif d in category_toggles:
        cat_key = category_toggles[d]
        alert_categories[cat_key] = not alert_categories.get(cat_key, True)
        save_settings()
        status = "🟢 مفعّل" if alert_categories[cat_key] else "🔴 معطّل"
        send_msg(f"✅ فئة {cat_key}: <b>{status}</b>", main_kb(), cid)
    elif d == "toggle_channel":
        # 🆕 تبديل الإرسال للقناة (المالك فقط)
        if not is_owner(cid):
            send_msg("🔒 هذا الخيار للمالك فقط.", main_kb(), cid)
            return
        if not CHANNEL_ID:
            send_msg("❌ لم يتم ضبط CHANNEL_ID في الإعدادات.", main_kb(), cid)
            return
        # تبديل القيمة: None → False, False → True, True → False
        current = is_channel_enabled()
        channel_enabled = not current
        save_settings()
        log.info(f"📢 Channel toggle: was={current}, now={channel_enabled}, saved to {SETTINGS_FILE}")
        # 🔧 إصلاح: تأكيد الحفظ
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                log.info(f"📢 Verified saved channel_enabled={saved.get('channel_enabled')}")
        except Exception as e:
            log.warning(f"📢 Could not verify save: {e}")
        status = "🟢 مفعّل" if channel_enabled else "🔴 معطّل"
        send_msg(f"📢 الإرسال للقناة: <b>{status}</b>\n\n💾 تم الحفظ في: <code>{SETTINGS_FILE}</code>", main_kb(), cid)
    elif d == "toggle_summary":
        # 🆕 تبديل الملخص اليومي (المالك فقط)
        if not is_owner(cid):
            send_msg("🔒 هذا الخيار للمالك فقط.", main_kb(), cid)
            return
        daily_summary_enabled = not daily_summary_enabled
        save_settings()
        status = "🟢 مفعّل" if daily_summary_enabled else "🔴 معطّل"
        send_msg(f"📅 الملخص اليومي: <b>{status}</b>", main_kb(), cid)
    elif d == "toggle_shutdown":
        # 🆕 إيقاف/تشغيل البوت الكامل (المالك فقط)
        if not is_owner(cid):
            send_msg("🔒 هذا الخيار للمالك فقط.", main_kb(), cid)
            return
        bot_shutdown = not bot_shutdown
        # 🆕 عند إعادة التشغيل، سجّل وقت الاستئناف لمنع إرسال الأخبار القديمة
        if not bot_shutdown:
            bot_resume_time = time.time()
            _skip_old_news_once = False  # إعادة ضبط العلم
            log.info(f"🔄 Bot resumed at {bot_resume_time} — old news will be skipped")
        else:
            log.warning(f"🛑 Bot SHUTDOWN by owner {cid}")
        save_settings()
        if bot_shutdown:
            send_msg("🔴 <b>تم إيقاف البوت نهائياً!</b>\n\n❌ لن تُرسل أي تنبيهات.\n❌ لن يستجيب لأي مستخدم (إلا المالك).\n\n💡 لإعادة التشغيل: الإعدادات → تشغيل البوت\n\nℹ️ عند إعادة التشغيل، لن تُرسل الأخبار القديمة المتراكمة أثناء الإيقاف.", main_kb(), cid)
            log.warning(f"🛑 Bot SHUTDOWN by owner {cid}")
        else:
            send_msg("🟢 <b>تم تشغيل البوت من جديد!</b>\n\n✅ التنبيهات مفعّلة.\n✅ الاستجابة عادية.\n⏭️ تم تجاوز الأخبار القديمة المتراكمة أثناء الإيقاف.", main_kb(), cid)
            log.info(f"✅ Bot RESTARTED by owner {cid}")
    elif d == "done_settings":
        send_msg("✅ تم حفظ الإعدادات", main_kb(), cid)


# ═══════════════════════════════════════════════════════════
# خادم Flask
# ═══════════════════════════════════════════════════════════
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        u = request.get_json()
        if u:
            threading.Thread(target=handle_update, args=(u,)).start()
    except:
        pass
    return jsonify({"ok": True})

@app.route("/")
def home():
    return jsonify({"status": "running", "bot": "news", "users": len(ALLOWED_USERS),
                    "sources": len(NEWS_SOURCES)})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/ping")
def ping():
    return jsonify({"pong": True})

# 🆕 endpoint خاص للـ keepalive - خفيف وسريع
@app.route("/keepalive")
def keepalive():
    return jsonify({"status": "alive", "ts": int(time.time())})


# ═══════════════════════════════════════════════════════════
# تشغيل البوت
# ═══════════════════════════════════════════════════════════
def self_ping():
    """🔧 إصلاح: ping كل 5 دقائق (Render ينام بعد 15 دقيقة)"""
    if not RENDER_URL:
        log.warning("RENDER_URL not set - self_ping disabled")
        return
    time.sleep(30)
    ping_count = 0
    while True:
        try:
            # 🔧 إصلاح: استخدام /keepalive (أخف) + ping كل 5 دقائق
            r = requests.get(f"{RENDER_URL}/keepalive", timeout=10)
            ping_count += 1
            if ping_count % 12 == 0:  # سجل كل ساعة (12 ping × 5 دقائق)
                log.info(f"💓 Keepalive: {ping_count} pings sent (status: {r.status_code})")
        except Exception as e:
            log.warning(f"self_ping err: {e}")
        # 🔧 إصلاح: 5 دقائق بدلاً من 10 (آمن ضد النوم)
        time.sleep(300)


# 🆕 إحصائيات يومية للملخص
_daily_stats = {
    "alerts_sent": 0,
    "important_found": 0,
    "total_scanned": 0,
    "categories": {"breaking": 0, "hack": 0, "etf": 0, "whale": 0, "tech": 0, "market": 0},
    "date": datetime.now(tz).strftime("%Y-%m-%d")
}

def update_daily_stats(alerts_sent=0, important=0, total=0, categories=None):
    """🆕 تحديث إحصائيات اليوم"""
    global _daily_stats
    # تحقق من تغير اليوم (إعادة تعيين الإحصائيات)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    if _daily_stats["date"] != today:
        log.info(f"📅 New day - resetting daily stats (was {_daily_stats['date']})")
        _daily_stats = {
            "alerts_sent": 0, "important_found": 0, "total_scanned": 0,
            "categories": {"breaking": 0, "hack": 0, "etf": 0, "whale": 0, "tech": 0, "market": 0},
            "date": today
        }
    _daily_stats["alerts_sent"] += alerts_sent
    _daily_stats["important_found"] += important
    _daily_stats["total_scanned"] += total
    if categories:
        for cat in categories:
            if cat in _daily_stats["categories"]:
                _daily_stats["categories"][cat] += 1


def build_daily_summary():
    """🆕 بناء ملخص يومي للأخبار"""
    today = datetime.now(tz).strftime("%Y-%m-%d")
    now_str = datetime.now(tz).strftime("%H:%M")
    msg = "📊 <b>الملخص اليومي للأخبار</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📅 التاريخ: {today}\n"
    msg += f"⏰ الوقت: {now_str}\n\n"
    msg += "📈 <b>إحصائيات اليوم:</b>\n"
    msg += f"   🔔 تنبيهات مُرسَلة: <b>{_daily_stats['alerts_sent']}</b>\n"
    msg += f"   📰 أخبار مهمة: <b>{_daily_stats['important_found']}</b>\n"
    msg += f"   📊 إجمالي فُحصت: <b>{_daily_stats['total_scanned']}</b>\n\n"
    # توزيع الفئات
    cats = _daily_stats["categories"]
    total_cats = sum(cats.values())
    if total_cats > 0:
        msg += "🏷️ <b>توزيع الفئات:</b>\n"
        # ترتيب الفئات تنازلياً
        sorted_cats = sorted(cats.items(), key=lambda x: -x[1])
        for cat, count in sorted_cats:
            if count > 0:
                icon = {"breaking": "🚨", "hack": "⚠️", "etf": "📊",
                        "whale": "🐋", "tech": "🔧", "market": "📈"}.get(cat, "📰")
                cat_name = {"breaking": "عاجل", "hack": "اختراق", "etf": "ETF",
                            "whale": "حيتان", "tech": "تقني", "market": "سوقي"}.get(cat, cat)
                pct = (count / total_cats) * 100
                msg += f"   {icon} {cat_name}: {count} ({pct:.0f}%)\n"
    else:
        msg += "ℹ️ لم تُرصد فئات محددة اليوم\n"
    msg += "\n"
    # آخر أخبار اليوم (آخر 5) - 🆕 فقط الأخبار المهمة المُصنَّفة
    try:
        news = get_all_news()
        if news:
            news = deduplicate_news(news)
            # فلترة أخبار اليوم فقط
            today_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            today_news = [n for n in news if n.get("timestamp", 0) >= today_start]
            # 🆕 فلترة: فقط الأخبار المهمة المُصنَّفة (استبعاد Reddit والإعلانات)
            important_today = []
            for item in today_news:
                source = item.get("source", "").lower()
                title = item.get("title", "").lower()
                # استبعاد Reddit والمحتوى الترويجي
                if "reddit" in source:
                    continue
                if any(spam in title for spam in ["tap to enter", "raffle", "giveaway", "win free"]):
                    continue
                # فقط الأخبار المُصنَّفة
                cats = classify_news(item)
                if cats:
                    important_today.append(item)
            if important_today:
                msg += f"📰 <b>آخر {min(5, len(important_today))} أخبار مهمة اليوم:</b>\n\n"
                for item in important_today[:5]:
                    title = item.get("title", "")
                    title_ar = item.get("title_ar", "")
                    if not title_ar:
                        title_ar = translate_to_arabic(title, force=True)
                    final_title = title_ar if title_ar else "⚠️ تعذرت الترجمة"
                    if len(final_title) > 80:
                        final_title = final_title[:77] + "..."
                    source = translate_source_name(item.get("source", ""))
                    msg += f"• {final_title}\n"
                    msg += f"  📡 {source}\n"
            else:
                msg += "ℹ️ لا توجد أخبار مهمة مُصنَّفة اليوم\n"
    except Exception as e:
        log.warning(f"daily summary news err: {e}")
    msg += "\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 <i>تم إنشاء هذا الملخص تلقائياً بواسطة البوت</i>"
    return msg


def daily_summary_loop():
    """🆕 يرسل ملخصاً يومياً في الساعة 23:59 بتوقيت المستخدم
    🔧 إصلاح: احترام daily_summary_enabled
    """
    global daily_summary_enabled
    log.info("📅 Daily summary loop started - will send at 23:59 daily")
    last_summary_date = None
    while True:
        try:
            # 🆕 إعادة تحميل الإعدادات
            load_settings()
            # 🆕 إذا كان الملخص معطّل، تخطّي
            if not daily_summary_enabled:
                time.sleep(300)
                continue
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            # تحقق: هل الساعة 23:59 (أو 23:58-00:02 للتسامح)؟
            # وهل لم نرسل الملخص اليوم؟
            if now.hour == 23 and now.minute >= 58 and last_summary_date != today:
                log.info(f"📅 Sending daily summary for {today}")
                # بناء الملخص
                msg = build_daily_summary()
                # إرسال لكل المستخدمين + القناة
                broadcast_alert(msg, None)
                last_summary_date = today
                log.info("📅 Daily summary sent successfully")
                # انتظر 5 دقائق قبل الفحص التالي (تجاوز نافذة 23:58-00:02)
                time.sleep(300)
                continue
            # فحص كل دقيقة
            time.sleep(60)
        except Exception as e:
            log.warning(f"daily_summary_loop err: {e}")
            time.sleep(60)


def start_bot():
    global _started
    if _started:
        return
    _started = True
    if not TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set!")
        return
    load_settings()
    load_sent_news()  # 🆕 تحميل الأخبار المُرسلة سابقاً
    wh = False
    if RENDER_URL:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                             params={"url": f"{RENDER_URL}/webhook"}, timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                wh = True
        except:
            pass
    alert_status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
    channel_status = "🟢 مفعّل" if (SEND_TO_CHANNEL and CHANNEL_ID) else "🔴 معطّل"
    msg = "📰 <b>بوت الأخبار — تم التشغيل</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📡 المصادر: {len(NEWS_SOURCES)} مصدر\n"
    msg += f"🔔 التنبيهات: {alert_status}\n"
    msg += f"👥 المستخدمون: {len(ALLOWED_USERS)}\n"
    msg += f"📢 القناة العامة: {channel_status}\n"
    if SEND_TO_CHANNEL and CHANNEL_ID:
        msg += f"   ┗ {CHANNEL_ID}\n"
    msg += "\n📥 أرسل /start للبدء"
    send_msg(msg)

    def run_with_restart(name, target_fn, restart_delay=30):
        while True:
            try:
                log.info(f"🔄 Starting {name} thread")
                target_fn()
            except Exception as e:
                log.error(f"❌ {name} crashed: {e} — restarting in {restart_delay}s")
            time.sleep(restart_delay)

    threading.Thread(target=lambda: run_with_restart("self_ping", self_ping),
                     daemon=True).start()
    threading.Thread(target=lambda: run_with_restart("news_scan", scan_news_loop),
                     daemon=True).start()
    # 🆕 thread الملخص اليومي (23:59)
    threading.Thread(target=lambda: run_with_restart("daily_summary", daily_summary_loop),
                     daemon=True).start()
    if not wh:
        def poll():
            global last_id
            last_id = 0
            while True:
                try:
                    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                                     params={"offset": last_id+1, "timeout": 25}, timeout=30)
                    if r.status_code == 200:
                        for u in r.json().get("result", []):
                            last_id = u.get("update_id", last_id)
                            handle_update(u)
                    else:
                        time.sleep(5)
                except:
                    time.sleep(5)
        threading.Thread(target=lambda: run_with_restart("polling", poll),
                         daemon=True).start()