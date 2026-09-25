# -*- coding: utf-8 -*-
"""
اختبار دخان (Smoke Test) — يتحقق من المنطق الأهم بدون شبكة:

1. تحميل الإعدادات من settings.yaml + التحقق من القوالب
2. التطبيع والبصمات واستخراج الأرقام وفحص السقوط
3. قاعدة SQLite: إنشاء الجداول، تسجيل العناصر، منع الازدواج، العلامات المائية،
   إضافة منشور، إعادة المحاولة، الصيانة
4. اكتشاف التشابه (RapidFuzz)
5. بناء نص المنشور من القالب مع HTML

التنفيذ:  python scripts/smoke_test.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import load_config, validate  # noqa: E402
from bot.db import Repository, create_engine, normalize_database_url  # noqa: E402
from bot.dedup import find_similar, similarity_score  # noqa: E402
from bot.normalizer import (  # noqa: E402
    content_hash, normalize_text, number_tokens, tokens_missing_in,
)
from bot.pipeline import build_post_text, clip_body  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "✅" if condition else "❌"
    print(f"{mark} {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        raise SystemExit(f"فشل الاختبار: {name}")


def test_normalizer() -> None:
    print("\n== التطبيع والبصمات والأرقام ==")
    t1 = "ارتفعَ البيتكوين 3.5% ليصل إلى $64,200 اليوم!"
    t2 = "ارتفع البيتكوين ٣٫٥٪ ليصل الي 64200$ اليوم"
    check("التطبيع يوحد الصيغ المتقاربة", similarity_score(normalize_text(t1), normalize_text(t2)) > 55,
          f"score={similarity_score(normalize_text(t1), normalize_text(t2)):.0f}")
    check("البصمة ثابتة للنص الواحد", content_hash(t1) == content_hash(t1))
    toks = number_tokens(t1)
    check("استخراج الأرقام والنسب والأسعار", {"3.5%", "$64,200"} <= toks, str(sorted(toks)))
    missing = tokens_missing_in(t1, "ارتفع البيتكوين ليصل إلى مستويات جديدة اليوم")
    check("فحص السقوط يلتقط الأرقام المفقودة", "3.5%" in missing and "$64,200" in missing, str(missing))
    missing2 = tokens_missing_in(t1, "ارتفع البيتكوين 3.5% ليصل إلى 64,200 دولار اليوم")
    check("لا إنذارات كاذبة عند الحفاظ على الأرقام", missing2 == [], str(missing2))


def test_dedup() -> None:
    print("\n== اكتشاف التشابه ==")
    published = [
        (101, normalize_text("Bitcoin surged past $100,000 as ETF inflows hit record highs this week"),
         normalize_text("ارتفع البيتكوين فوق 100,000 دولار مع تدفقات قياسية لصناديق ETF")),
    ]
    same_news = "Bitcoin breaks above $100k as ETF inflows reach record levels this week"
    match = find_similar(normalize_text(same_news), "", published, threshold=60)
    check("يلتقط نفس الخبر بصياغة إنجليزية مختلفة", match is not None,
          f"score={match[1]:.0f}" if match else "")
    other = "Ethereum staking rewards dropped significantly after the latest network upgrade"
    match2 = find_similar(normalize_text(other), "", published, threshold=60)
    check("لا يعتبر خبراً مختلفاً تشابهاً", match2 is None)
    final_match = find_similar("", normalize_text(
        "ارتفع البيتكوين فوق 100,000 دولار مع تدفقات قياسية لصناديق ETF"), published, threshold=60)
    check("يلتقط التطابق عبر النص النهائي", final_match is not None)


def test_post_text() -> None:
    print("\n== بناء المنشور ==")
    template = "📰 <b>{title}</b>\n\n{body}\n\n{ticker_line}📌 المصدر: {source}\n"
    text = build_post_text(template, "ارتفاع مفاجئ للبيتكوين", "نص الخبر <الاختباري> هنا 3.5%",
                           "CoinDesk", "BTC")
    check("القالب يعمل مع Ticker", "💠 <b>BTC</b>" in text and "CoinDesk" in text)
    text2 = build_post_text(template, "عنوان", "نص", "CoinDesk", None)
    check("سطر Ticker يُزال عند غيابه", "💠" not in text2)
    long_body = "كلمة " * 300
    clipped = clip_body(long_body, 200)
    check("قص النص الطويل", len(clipped) <= 205, f"len={len(clipped)}")


async def test_database() -> None:
    print("\n== قاعدة البيانات (SQLite) ==")
    db_url = normalize_database_url(None, DATA_DIR / "smoke")
    repo = Repository(create_engine(db_url))
    await repo.create_all()

    base_row = {
        "source_channel_id": "123456",
        "source_message_id": 500,
        "source_name": "CoinDesk",
        "raw_text": "Bitcoin ETF inflows hit $1.2B this week (3.5% up)",
        "content_hash": content_hash("Bitcoin ETF inflows hit $1.2B this week (3.5% up)"),
        "state": "pending",
        "media_type": "photo",
        "has_media": 1,
    }
    new_ids = await repo.record_items([dict(base_row)])
    check("تسجيل عنصر جديد", len(new_ids) == 1)

    again = await repo.record_items([dict(base_row)])
    check("منع الازدواج بنفس القناة والرسالة", again == [])

    rows = await repo.load_rows(new_ids)
    row = rows[0]
    check("البيانات محفوظة صحيحة", row.state == "pending" and row.has_media == 1 and row.source_name == "CoinDesk")

    await repo.set_watermark("123456", 500)
    wm = await repo.get_watermark("123456")
    check("العلامة المائية تُقرأ وتُحدّث", wm == 500)
    await repo.set_watermark("123456", 610)
    check("ترقية العلامة المائية", await repo.get_watermark("123456") == 610)

    await repo.mark_state(row.id, "published", title="عنوان", final_text="نص نهائي", retry_count=0)
    await repo.add_published(
        content_hash=row.content_hash,
        normalized_raw=normalize_text(row.raw_text),
        normalized_final=normalize_text("نص نهائي"),
        title="عنوان", source_channel_id="123456", dest_message_id=777,
    )
    pub_hash = await repo.find_published_by_hash(row.content_hash)
    check("البحث بالبصمة يجد المنشور", pub_hash is not None)

    recent = await repo.recent_published(window_hours=72)
    check("سجل المنشورات متاح للتشابه", len(recent) == 1 and recent[0][0] == pub_hash)

    fail_row2 = dict(base_row, source_message_id=501)
    ids2 = await repo.record_items([fail_row2])
    await repo.mark_state(ids2[0], "failed", error="network down", retry_count=1)
    retryable = await repo.fetch_retryable(max_retries=3, max_age_hours=24, batch_size=10)
    check("الصف الفاشل يدخل إعادة المحاولة", any(r.id == ids2[0] for r in retryable))

    exhausted = await repo.record_items([dict(base_row, source_message_id=502)])
    await repo.mark_state(exhausted[0], "failed", error="dead", retry_count=3)
    retryable2 = await repo.fetch_retryable(max_retries=3, max_age_hours=24, batch_size=10)
    check("الصف المستنفد لا يُعاد", not any(r.id == exhausted[0] for r in retryable2))

    deleted = await repo.housekeeping(retention_days=30)
    check("الصيانة تعمل بدون أخطاء", isinstance(deleted, dict))

    counts = await repo.counts_by_state()
    check("الإحصاءات", counts.get("published", 0) >= 1, str(counts))
    await repo.dispose()


def test_config() -> None:
    print("\n== الإعدادات ==")
    settings, secrets = load_config()
    check("قنوات المصدر من settings.yaml", len(settings.source_channels) >= 1, str(settings.source_channels))
    check("قناة الوجهة مضبوطة", bool(settings.destination_channel))
    check("قالب المنشور يحوي المتغيرات", all(p in settings.post_template for p in ("{title}", "{body}", "{source}")))
    check("عتبة التشابه داخل المدى", 50 <= settings.dedup.similarity_threshold <= 100)
    missing_before = []
    try:
        validate(settings, secrets)
    except Exception as exc:  # الأسرار غير مضبوطة في بيئة الاختبار — يجب أن يفشل برسالة واضحة
        missing_before.append(str(exc))
    check("التحقق يرفض غياب الأسرار برسالة واضحة", bool(missing_before), missing_before[0].splitlines()[0][:80])


def main() -> None:
    print("بدء اختبار الدخان...")
    test_normalizer()
    test_dedup()
    test_post_text()
    test_config()
    asyncio.run(test_database())
    print("\n🎉 كل اختبارات الدخان نجحت — النظام جاهز.")


if __name__ == "__main__":
    main()
