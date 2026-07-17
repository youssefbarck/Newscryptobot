"""
📰 بوت أخبار العملات الرقمية - نقطة الدخول
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
يدعم وضعين:
1) Render (افتراضي): start_bot() - بوت دائم التشغيل مع Flask + webhook/polling
2) GitHub Actions: GITHUB_ACTIONS=true → دورة واحدة فقط ثم خروج

المكونات:
- config.py       → الإعدادات، التخزين، إدارة المستخدمين
- filters.py      → تصنيف الأخبار، الفلاتر، الكلمات المفتاحية
- rss.py          → جلب الأخبار من المصادر RSS
- translate.py    → الترجمة للعربية (Gemini → Groq → OpenRouter)
- telegram_bot.py → البوت، التنسيق، البث، Flask، حلقات الفحص
"""

import os, time, traceback

from config import (
    TOKEN, CHANNEL_ID, SEND_TO_CHANNEL, channel_enabled,
    load_settings, save_settings, load_sent_news, save_sent_news,
    sent_news_hashes, _cache,
)
from filters import classify_news, CRYPTO_CONTEXT_KEYWORDS, REJECTION_KEYWORDS
from rss import get_all_news, deduplicate_news, news_hash, fetch_etf_flows
from translate import translate_news_item
from telegram_bot import (
    fmt_news_item, broadcast_alert, start_bot,
)

if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RUN_MODE") == "oneshot":
        # === وضع GitHub Actions: دورة واحدة ===
        print("=" * 60)
        print("🤖 Running in GitHub Actions mode (one-shot)")
        print("=" * 60)

        if not TOKEN:
            print("❌ TELEGRAM_BOT_TOKEN not set!")
            exit(1)

        # تحميل الإعدادات والأخبار المُرسلة سابقاً
        load_settings()
        load_sent_news()

        # 🔧 حماية: لو لا توجد أي هاشات محفوظة = أول تشغيل أو خطأ
        # نسجّل وقت البدء ونرفض أي خبر أقدم من هذا الوقت
        _session_start = time.time()
        if len(sent_news_hashes) == 0:
            print("⚠️ No sent hashes loaded — SAFETY MODE: only news AFTER this moment will be sent")
            print(f"   Session start: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        # تفعيل القناة إذا كانت معطّلة في الإعدادات المحفوظة
        if CHANNEL_ID and not channel_enabled:
            channel_enabled = True
            save_settings()

        try:
            # مسح الكاش
            if "all_news" in _cache:
                del _cache["all_news"]
            news = get_all_news()
            if not news:
                print("⚠️ لا أخبار متاحة. إعادة المحاولة بعد 5 دقائق.")
                exit(0)

            news = deduplicate_news(news)
            now = time.time()
            alerts_sent = 0
            total_news = len(news)
            important_news = 0
            already_sent = 0
            old_news_skipped = 0

            print(f"📰 إجمالي الأخبار: {total_news}")

            # نفحص آخر 40 خبر
            for item in news[:40]:
                item_ts = item.get("timestamp", 0)

                # 🔧 حماية timestamp: خبر بدون timestamp أو أقدم من 3 ساعات
                if item_ts > 0 and (now - item_ts) > 10800:
                    old_news_skipped += 1
                    h_old = news_hash(item)
                    if h_old not in sent_news_hashes:
                        sent_news_hashes.add(h_old)
                    continue

                # 🔧 حماية Safety Mode: لو لا هاشات محفوظة، ارفض كل الأخبار
                # التي timestampها قبل بدء الجلسة
                if len(sent_news_hashes) == 0 and item_ts > 0 and item_ts < _session_start:
                    old_news_skipped += 1
                    h_old = news_hash(item)
                    sent_news_hashes.add(h_old)
                    continue

                news_text = (item.get("title", "") + " " + item.get("summary", "")).lower()

                # (1) سياق الكريبتو
                has_crypto_context = any(kw in news_text for kw in CRYPTO_CONTEXT_KEYWORDS)

                # ✅ القبول: سياق كريبتو كافي
                if not has_crypto_context:
                    continue

                # (2) كلمات الرفض
                has_rejection = any(kw in news_text for kw in REJECTION_KEYWORDS)
                if has_rejection:
                    continue

                # رفض مصدر Reddit
                if "reddit" in (item.get("source", "") or "").lower():
                    continue

                important_news += 1

                h = news_hash(item)
                if h in sent_news_hashes:
                    already_sent += 1
                    continue

                # تحديث الذاكرة
                sent_news_hashes.add(h)
                save_sent_news()

                # ترجمة الخبر قبل الإرسال
                translate_news_item(item)

                # فحص اكتمال الترجمة (translate_to_arabic تعيد None للمقطوع)
                title_ar = item.get("title_ar", "")
                if not title_ar:
                    print(f"  ⏭️ Skipping (translation None): {item.get('title', '')[:60]}...")
                    continue

                # إرسال للقناة والمستخدمين
                msg = fmt_news_item(item, show_summary=True, translate=True)
                if not msg:
                    print(f"  ⏭️ Skipping (translation failed): {item.get('title', '')[:60]}...")
                    continue
                image_url = item.get("image", "")
                broadcast_alert(msg, image_url)
                alerts_sent += 1
                print(f"  ✉️ {item.get('title', '')[:60]}...")
                time.sleep(1.5)

            print("=" * 60)
            print(f"📊 النتائج:")
            print(f"   • إجمالي الأخبار: {total_news}")
            print(f"   • أخبار مهمة: {important_news}")
            print(f"   • تم إرسالها: {alerts_sent}")
            print(f"   • أُرسلت سابقاً: {already_sent}")
            print(f"   • أخبار قديمة: {old_news_skipped}")
            print("=" * 60)

            # ═══════════════════════════════════════════════
            # 📊 منشور التدفقات اليومي (مرة واحدة يومياً)
            # ═══════════════════════════════════════════════
            try:
                etf = fetch_etf_flows()
                if etf:
                    etf_hash = f"etf_{etf['date']}"
                    if etf_hash not in sent_news_hashes:
                        sent_news_hashes.add(etf_hash)
                        # بناء الرسالة
                        btc_sign = "+" if etf['btc_total'] >= 0 else ""
                        eth_sign = "+" if etf['eth_total'] >= 0 else ""
                        btc_emoji = "📈" if etf['btc_total'] >= 0 else "📉"
                        eth_emoji = "📈" if etf['eth_total'] >= 0 else "📉"
                        msg = f"📊 صافي تدفقات صناديق ETF — {etf['date']}\n\n"
                        msg += f"{btc_emoji} Bitcoin ETF: {btc_sign}{etf['btc_total']:.1f} مليون $"
                        # أهم 3 صناديق
                        top_btc = sorted(etf['btc_funds'].items(), key=lambda x: -x[1])[:3]
                        btc_parts = [f"{t} {v:+.1f}M" for t, v in top_btc if v != 0]
                        if btc_parts:
                            msg += f"  ({', '.join(btc_parts)})"
                        msg += "\n"
                        msg += f"{eth_emoji} Ethereum ETF: {eth_sign}{etf['eth_total']:.1f} مليون $"
                        top_eth = sorted(etf['eth_funds'].items(), key=lambda x: -x[1])[:3]
                        eth_parts = [f"{t} {v:+.1f}M" for t, v in top_eth if v != 0]
                        if eth_parts:
                            msg += f"  ({', '.join(eth_parts)})"
                        msg += "\n\n✉️"
                        broadcast_alert(msg, "")
                        print(f"  📊 ETF flows sent: {etf['date']}")
                        time.sleep(1)
            except Exception as e:
                print(f"  ⚠️ ETF flows error: {e}")

            save_sent_news(force=True)
            print("✅ انتهى. سيتم التشغيل التالي بعد 5 دقائق.")

        except SystemExit:
            save_sent_news(force=True)
            raise
        except Exception as e:
            save_sent_news(force=True)
            print(f"❌ خطأ: {e}")
            traceback.print_exc()
            exit(0)
    else:
        # === وضع Render: تشغيل دائم ===
        start_bot()