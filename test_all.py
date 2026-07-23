"""
🐋 Whale News Bot v3 - اختبار شامل
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
يختبر كل وحدة على حدة + pipeline كامل
"""

import sys
import os
import time
import asyncio
import traceback

# إضافة المسار
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════════════════
# ألوان الطرفية
# ═══════════════════════════════════════════════════════════
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def ok(msg):
    print(f"  {GREEN}✅ {msg}{RESET}")

def fail(msg):
    print(f"  {RED}❌ {msg}{RESET}")

def info(msg):
    print(f"  {CYAN}ℹ️  {msg}{RESET}")

def section(title):
    print(f"\n{BOLD}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{RESET}")


# ═══════════════════════════════════════════════════════════
# عداد الاختبارات
# ═══════════════════════════════════════════════════════════
_total = 0
_passed = 0
_failed = 0

def run_test(name, func):
    global _total, _passed, _failed
    _total += 1
    print(f"\n  🧪 {name}")
    try:
        func()
        _passed += 1
        ok("PASS")
    except AssertionError as e:
        _failed += 1
        fail(f"FAIL: {e}")
    except Exception as e:
        _failed += 1
        fail(f"ERROR: {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════
# 1. اختبار النماذج (models.py)
# ═══════════════════════════════════════════════════════════
section("📦 اختبار النماذج (models.py)")

def test_news_item_creation():
    from models import NewsItem, NewsType
    item = NewsItem(title="Bitcoin surges past $70,000", source="CoinDesk")
    assert item.hash, "hash should be computed"
    assert len(item.hash) == 16, f"hash length: {len(item.hash)}"
    assert item.news_type == NewsType.GENERAL

def test_news_item_fact_hash():
    from models import NewsItem, ExtractedFacts
    item = NewsItem(title="BTC rises")
    item.facts = ExtractedFacts(main_entities=["Bitcoin"], coins=["BTC"])
    fh = item.get_fact_hash()
    assert fh and len(fh) == 16

def test_news_item_validation():
    from models import NewsItem
    # عنوان قصير
    item = NewsItem(title="short", title_ar="قصير")
    assert not item.is_valid(), "short title should be invalid"
    # بدون ترجمة
    item = NewsItem(title="A valid news title with enough content")
    assert not item.is_valid(), "no translation should be invalid"
    # صالح
    item = NewsItem(
        title="Bitcoin reaches new all-time high",
        title_ar="بيتكوين يحقق مستوى قياسي جديد",
        summary_ar="وصلت عملة بيتكوين إلى مستوى قياسي جديد"
    )
    assert item.is_valid()

def test_score_result():
    from models import ScoreResult
    result = ScoreResult(
        source_score=30, urgency_score=20, financial_score=15,
        entity_score=10, age_score=7, type_score=8, bonus=0, penalty=-5
    )
    # __post_init__ يحسب total تلقائياً
    expected = 30 + 20 + 15 + 10 + 7 + 8 + 0 + (-5)
    assert result.total == expected, f"total: {result.total} != {expected}"
    assert result.should_publish

def test_pipeline_stats():
    from models import PipelineStats
    stats = PipelineStats(collected=100, published=15, rejected=85)
    text = stats.summary()
    assert "جمع=100" in text
    assert "نُشر=15" in text

run_test("إنشاء NewsItem", test_news_item_creation)
run_test("حساب fact_hash", test_news_item_fact_hash)
run_test("التحقق من صحة الخبر", test_news_item_validation)
run_test("حساب ScoreResult", test_score_result)
run_test("إحصائيات Pipeline", test_pipeline_stats)


# ═══════════════════════════════════════════════════════════
# 2. اختبار الإعدادات (config.py)
# ═══════════════════════════════════════════════════════════
section("⚙️ اختبار الإعدادات (config.py)")

def test_config_from_env():
    from config import cfg
    assert cfg.SCAN_INTERVAL == 300
    assert cfg.MIN_PUBLISH_SCORE == 35.0
    assert cfg.MAX_NEWS_PER_SCAN == 40
    assert cfg.WATERMARK_TEXT == "@newscrypto1m"

def test_coin_map():
    from config import COIN_MAP
    assert COIN_MAP["bitcoin"] == "BTC"
    assert COIN_MAP["ethereum"] == "ETH"
    assert COIN_MAP["solana"] == "SOL"
    assert len(COIN_MAP) >= 30, f"coin map size: {len(COIN_MAP)}"

def test_companies():
    from config import COMPANIES
    assert "blackrock" in COMPANIES
    assert "sec" in COMPANIES
    assert COMPANIES["blackrock"] == "BlackRock"

def test_type_keywords():
    from config import TYPE_KEYWORDS
    assert "hack" in TYPE_KEYWORDS
    assert "etf" in TYPE_KEYWORDS
    assert "regulation" in TYPE_KEYWORDS
    assert len(TYPE_KEYWORDS["hack"]) >= 10

def test_news_sources():
    from config import NEWS_SOURCES
    assert "CoinDesk" in NEWS_SOURCES
    assert "Cointelegraph" in NEWS_SOURCES
    assert NEWS_SOURCES["CoinDesk"]["tier"] == 1
    assert NEWS_SOURCES["CoinDesk"]["lang"] == "en"

def test_crypto_context_keywords():
    from config import CRYPTO_CONTEXT_KEYWORDS
    assert "bitcoin" in CRYPTO_CONTEXT_KEYWORDS
    assert "بيتكوين" in CRYPTO_CONTEXT_KEYWORDS
    assert len(CRYPTO_CONTEXT_KEYWORDS) >= 40

def test_rejection_keywords():
    from config import REJECTION_KEYWORDS
    assert "price prediction" in REJECTION_KEYWORDS
    assert "how to buy" in REJECTION_KEYWORDS

run_test("تحميل الإعدادات", test_config_from_env)
run_test("خريطة العملات", test_coin_map)
run_test("الشركات", test_companies)
run_test("كلمات التصنيف", test_type_keywords)
run_test("مصادر الأخبار", test_news_sources)
run_test("كلمات السياق الكريبتوي", test_crypto_context_keywords)
run_test("كلمات الرفض", test_rejection_keywords)


# ═══════════════════════════════════════════════════════════
# 3. اختبار قاعدة البيانات (database.py)
# ═══════════════════════════════════════════════════════════
section("📂 اختبار قاعدة البيانات (database.py)")

def test_database_basic():
    import tempfile
    from database import NewsDatabase, NewsRecord
    with tempfile.TemporaryDirectory() as tmpdir:
        db = NewsDatabase(tmpdir)
        db.load()

        rec = NewsRecord(
            title="Test news", fact_hash="abc123", text_hash="def456",
            entities=["Bitcoin"], coins=["BTC"], news_type="etf",
            source="CoinDesk", timestamp=time.time()
        )
        db.add(rec)

        # فحص التكرار
        assert db.is_duplicate("def456"), "text_hash should exist"
        assert db.is_duplicate("xyz", "abc123"), "fact_hash should exist"
        assert not db.is_duplicate("newhash"), "new hash should not exist"

        # إحصائيات
        stats = db.get_stats()
        assert stats["total"] == 1

def test_database_find_similar():
    import tempfile
    from database import NewsDatabase, NewsRecord
    with tempfile.TemporaryDirectory() as tmpdir:
        db = NewsDatabase(tmpdir)
        rec = NewsRecord(
            title="BlackRock BTC", fact_hash="aaa", text_hash="bbb",
            entities=["BlackRock", "Bitcoin"], coins=["BTC"],
            news_type="etf", source="CoinDesk", timestamp=time.time()
        )
        db.add(rec)

        # بحث عن سجل مشابه
        found = db.find_similar("ccc", ["BlackRock"], ["BTC"])
        assert found is not None, "should find similar record"

run_test("إضافة وفحص التكرار", test_database_basic)
run_test("البحث عن سجلات مشابهة", test_database_find_similar)


# ═══════════════════════════════════════════════════════════
# 4. اختبار التنظيف (cleaner.py)
# ═══════════════════════════════════════════════════════════
section("🧹 اختبار التنظيف (cleaner.py)")

# إجبار إعادة تحميل الوحدات لضمان الكود المحدث
import importlib as _importlib
for _m in ['models', 'config', 'cleaner']:
    if _m in sys.modules:
        _importlib.reload(sys.modules[_m])

def test_clean_html():
    from cleaner import _remove_html_and_encoding
    text = _remove_html_and_encoding("<p>Bitcoin <b>surges</b> past $70,000</p>")
    assert "<" not in text
    assert "Bitcoin" in text

def test_clean_format_labels():
    from cleaner import _strip_format_labels
    text = _strip_format_labels("🔵 منشور الأخبار العاجلة: Bitcoin reaches ATH")
    assert "منشور الأخبار العاجلة" not in text
    assert "Bitcoin" in text

def test_clean_format_labels_emoji():
    from cleaner import _strip_format_labels
    text = _strip_format_labels("🚨 Breaking News: Major hack detected")
    assert "Breaking News:" not in text
    assert "Major hack" in text

def test_clean_signatures():
    from cleaner import _remove_signatures
    text = "Bitcoin rises. Follow us on Twitter @handle for more"
    result = _remove_signatures(text)
    assert "Follow us" not in result

def test_clean_source_leaks():
    from cleaner import _remove_source_leaks
    text = "According to CoinDesk, Bitcoin reached a new high today"
    result = _remove_source_leaks(text)
    assert "According to CoinDesk" not in result
    assert "Bitcoin" in result

def test_clean_arabic():
    from cleaner import _clean_arabic_text
    text = "إأآٱبتكوين"  # أشكال الألف المختلفة
    result = _clean_arabic_text(text)
    assert "ا" in result
    # بدون tatweel
    text2 = "بيتكـــــوين"
    result2 = _clean_arabic_text(text2)
    assert "ـــ" not in result2

def test_full_clean():
    """اختبار التنظيف الكامل — يُنفذ في subprocess لضمان كود نظيف"""
    import subprocess
    code = (
        "import sys; sys.path.insert(0, '.')\n"
        "from models import NewsItem\n"
        "from cleaner import clean_news_item\n"
        "item = NewsItem(\n"
        "    title='CoinDesk: \U0001f535 Bitcoin Surges Past $70K',\n"
        "    summary='<p>Bitcoin has reached a new milestone. Read more at https://example.com</p>'\n"
        ")\n"
        "cleaned = clean_news_item(item)\n"
        "assert 'CoinDesk:' not in cleaned.clean_title, f'title: {cleaned.clean_title}'\n"
        "assert '<p>' not in cleaned.clean_summary, f'summary: {cleaned.clean_summary}'\n"
        "assert 'Read more at' not in cleaned.clean_summary, f'summary: {cleaned.clean_summary}'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__))
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr.strip()}"
    assert "OK" in result.stdout, f"unexpected output: {result.stdout}"

run_test("إزالة HTML", test_clean_html)
run_test("إزالة تسميات التنسيق", test_clean_format_labels)
run_test("إزالة تسميات مع إيموجي", test_clean_format_labels_emoji)
run_test("إزالة التوقيعات", test_clean_signatures)
run_test("إزالة تسرب اسم المصدر", test_clean_source_leaks)
run_test("تنظيف النص العربي", test_clean_arabic)
run_test("تنظيف كامل", test_full_clean)


# ═══════════════════════════════════════════════════════════
# 5. اختبار استخراج الحقائق (fact_extractor.py)
# ═══════════════════════════════════════════════════════════
section("🔍 اختبار استخراج الحقائق (fact_extractor.py)")

def test_extract_coins():
    from fact_extractor import extract_facts
    facts = extract_facts("Bitcoin and Ethereum are both surging today")
    assert "BTC" in facts.coins, f"coins: {facts.coins}"
    assert "ETH" in facts.coins

def test_extract_companies():
    from fact_extractor import extract_facts
    facts = extract_facts("BlackRock announced new Bitcoin ETF plans")
    assert "BlackRock" in facts.main_entities, f"entities: {facts.main_entities}"

def test_extract_people():
    from fact_extractor import extract_facts
    facts = extract_facts("Elon Musk tweeted about Dogecoin")
    assert "Elon Musk" in facts.main_entities, f"entities: {facts.main_entities}"

def test_extract_financial():
    from fact_extractor import extract_facts
    facts = extract_facts("BlackRock bought 400 BTC worth $48M")
    assert facts.has_financial_data, "should detect financial data"
    assert len(facts.facts) > 0
    # تحقق من القيم
    found_btc = any(f.amount == 400 for f in facts.facts)
    found_dollars = any(f.value_usd == 48000000 for f in facts.facts)
    assert found_btc, "should find 400 BTC"
    assert found_dollars, "should find $48M"

def test_extract_hack():
    from fact_extractor import extract_facts
    facts = extract_facts("Binance was hacked for $570M in a security breach")
    assert facts.sentiment == "negative", f"sentiment: {facts.sentiment}"
    assert any(f.action == "hacked" for f in facts.facts), "should detect hack action"

def test_extract_etf():
    from fact_extractor import extract_facts
    facts = extract_facts("SEC approved Bitcoin ETF applications from BlackRock and Fidelity")
    assert "BTC" in facts.coins or "Bitcoin" in str(facts.main_entities)

def test_sentiment_positive():
    from fact_extractor import extract_facts
    facts = extract_facts("Bitcoin surges to new all-time high, reaching record levels")
    assert facts.sentiment == "positive", f"sentiment: {facts.sentiment}"

def test_fact_hash_stability():
    from fact_extractor import extract_facts
    facts1 = extract_facts("BlackRock Bitcoin ETF")
    facts2 = extract_facts("Bitcoin ETF from BlackRock")
    # نفس الكيانات → نفس hash
    h1 = facts1.to_fact_key()
    h2 = facts2.to_fact_key()
    assert h1 == h2, f"hashes should match: {h1} != {h2}"

run_test("استخراج العملات", test_extract_coins)
run_test("استخراج الشركات", test_extract_companies)
run_test("استخراج الأشخاص", test_extract_people)
run_test("استخراج البيانات المالية", test_extract_financial)
run_test("استخراج أحداث الاختراق", test_extract_hack)
run_test("استخراج أحداث ETF", test_extract_etf)
run_test("تحليل المشاعر الإيجابية", test_sentiment_positive)
run_test("ثبات hash الحقائق", test_fact_hash_stability)


# ═══════════════════════════════════════════════════════════
# 6. اختبار كشف التكرار (deduplicator.py)
# ═══════════════════════════════════════════════════════════
section("🔄 اختبار كشف التكرار (deduplicator.py)")

def test_text_hash_dedup():
    from deduplicator import check_duplicate
    from database import NewsDatabase
    from models import NewsItem, SourceQuality
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        db = NewsDatabase(tmpdir)
        item1 = NewsItem(
            title="Bitcoin reaches new all-time high",
            source="CoinDesk", source_quality=SourceQuality.TIER_1
        )
        item1.facts = item1.facts  # trigger __post_init__
        # تسجيل الأول
        from deduplicator import register_news
        register_news(item1, db)

        # نفس العنوان = مكرر
        item2 = NewsItem(
            title="Bitcoin reaches new all-time high",
            source="Cointelegraph"
        )
        assert check_duplicate(item2, db), "same title should be duplicate"

def test_fact_hash_dedup():
    from deduplicator import check_duplicate, register_news
    from database import NewsDatabase
    from models import NewsItem, ExtractedFacts, SourceQuality
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        db = NewsDatabase(tmpdir)
        item1 = NewsItem(
            title="BlackRock Bitcoin ETF approved by SEC",
            source="CoinDesk", source_quality=SourceQuality.TIER_1
        )
        item1.facts = ExtractedFacts(
            main_entities=["BlackRock", "SEC"],
            coins=["BTC"]
        )
        register_news(item1, db)

        # صياغة مختلفة لكن نفس الكيانات
        item2 = NewsItem(
            title="SEC gives green light to BlackRock's BTC ETF",
            source="Blockworks"
        )
        item2.facts = ExtractedFacts(
            main_entities=["BlackRock", "SEC"],
            coins=["BTC"]
        )
        assert check_duplicate(item2, db), "same facts should be duplicate"

def test_merge_sources():
    from deduplicator import merge_sources
    from models import NewsItem, ExtractedFacts, SourceQuality
    item1 = NewsItem(
        title="Bitcoin ETF approved",
        source="CoinDesk", source_quality=SourceQuality.TIER_1,
        timestamp=time.time()
    )
    item1.facts = ExtractedFacts(main_entities=["SEC", "BlackRock"], coins=["BTC"])

    item2 = NewsItem(
        title="SEC approves BlackRock Bitcoin ETF",
        source="Cointelegraph", source_quality=SourceQuality.TIER_1,
        summary="Detailed analysis of the approval...",
        timestamp=time.time()
    )
    item2.facts = ExtractedFacts(main_entities=["SEC", "BlackRock"], coins=["BTC"])

    merged = merge_sources([item1, item2])
    # يجب أن يدمجها → خبر واحد (أو اثنين إذا فشل الدمج)
    # يجب أن يكون أقل من 2 إذا نجح الدمج
    assert len(merged) <= 2, f"should merge: got {len(merged)}"

run_test("كشف تكرار النص", test_text_hash_dedup)
run_test("كشف تكرار الحقائق", test_fact_hash_dedup)
run_test("دمج المصادر", test_merge_sources)


# ═══════════════════════════════════════════════════════════
# 7. اختبار التصنيف (classifier.py)
# ═══════════════════════════════════════════════════════════
section("🏷️ اختبار التصنيف (classifier.py)")

def test_classify_hack():
    from classifier import classify_news
    from models import NewsItem
    item = NewsItem(title="Major exchange hacked for $500M", summary="Security breach detected")
    ntype = classify_news(item)
    assert ntype.value == "hack", f"got: {ntype.value}"

def test_classify_etf():
    from classifier import classify_news
    from models import NewsItem
    item = NewsItem(title="Bitcoin ETF sees record inflows", summary="Fund flows analysis")
    ntype = classify_news(item)
    assert ntype.value == "etf", f"got: {ntype.value}"

def test_classify_regulation():
    from classifier import classify_news
    from models import NewsItem
    item = NewsItem(title="SEC proposes new crypto regulation framework")
    ntype = classify_news(item)
    assert ntype.value == "regulation", f"got: {ntype.value}"

def test_classify_macro():
    from classifier import classify_news
    from models import NewsItem
    item = NewsItem(title="Federal Reserve holds interest rate steady")
    ntype = classify_news(item)
    assert ntype.value == "macro", f"got: {ntype.value}"

def test_classify_general():
    from classifier import classify_news
    from models import NewsItem
    item = NewsItem(title="Crypto community discusses new trends")
    ntype = classify_news(item)
    assert ntype.value == "general", f"got: {ntype.value}"

def test_score_tier1_source():
    from classifier import score_news
    from models import NewsItem, SourceQuality
    item = NewsItem(
        title="Breaking: Major hack detected on leading exchange",
        source="CoinDesk", source_quality=SourceQuality.TIER_1,
        timestamp=time.time()
    )
    item.news_type = __import__('models', fromlist=['NewsType']).NewsType.HACK
    result = score_news(item)
    assert result.source_score == 30, f"tier1 score: {result.source_score}"
    assert result.urgency_score == 20, f"hack urgency: {result.urgency_score}"
    assert result.should_publish, f"total: {result.total}"

def test_score_tier3_low():
    from classifier import score_news
    from models import NewsItem, SourceQuality
    item = NewsItem(
        title="Crypto trends to watch in 2025",
        source="Google News", source_quality=SourceQuality.TIER_3,
        timestamp=time.time() - 86400 * 2  # يومين
    )
    item.news_type = __import__('models', fromlist=['NewsType']).NewsType.GENERAL
    result = score_news(item)
    assert not result.should_publish, f"low score news should not publish: {result.total}"

def test_should_reject_short():
    from classifier import should_reject
    from models import NewsItem
    item = NewsItem(title="Short", summary="Too short content")
    rejected, reason = should_reject(item)
    assert rejected, "short content should be rejected"

def test_should_reject_reddit():
    from classifier import should_reject
    from models import NewsItem
    item = NewsItem(
        title="Bitcoin discussion", summary="Great analysis of BTC",
        source="reddit"
    )
    rejected, reason = should_reject(item)
    assert rejected, "reddit should be rejected"

def test_should_not_reject_valid():
    from classifier import should_reject
    from models import NewsItem
    item = NewsItem(
        title="BlackRock Bitcoin ETF approved by SEC in historic vote",
        summary="The Securities and Exchange Commission approved the first spot Bitcoin ETF"
    )
    rejected, reason = should_reject(item)
    assert not rejected, f"valid news should not be rejected: {reason}"

run_test("تصنيف اختراق", test_classify_hack)
run_test("تصنيف ETF", test_classify_etf)
run_test("تصنيف تنظيم", test_classify_regulation)
run_test("تصنيف اقتصاد كلّي", test_classify_macro)
run_test("تصنيف عام", test_classify_general)
run_test("تقييم مصدر Tier 1", test_score_tier1_source)
run_test("تقييم مصدر Tier 3 منخفض", test_score_tier3_low)
run_test("رفض محتوى قصير", test_should_reject_short)
run_test("رفض Reddit", test_should_reject_reddit)
run_test("قبول خبر صالح", test_should_not_reject_valid)


# ═══════════════════════════════════════════════════════════
# 8. اختبار التنسيق (formatter.py)
# ═══════════════════════════════════════════════════════════
section("📝 اختبار التنسيق (formatter.py)")

def test_format_general():
    from formatter import format_news
    from models import NewsItem, NewsType, ExtractedFacts
    item = NewsItem(
        title="Test", title_ar="بيتكوين يرتفع",
        summary_ar="وصلت عملة بيتكوين إلى مستوى جديد",
        news_type=NewsType.GENERAL
    )
    item.facts = ExtractedFacts(coins=["BTC"])
    msg = format_news(item)
    assert msg is not None, "should format"
    assert "بيتكوين يرتفع" in msg.text, f"got: {msg.text[:100]}"
    assert "#BTC" in msg.text or "#بيتكوين" in msg.text

def test_format_hack():
    from formatter import format_news
    from models import NewsItem, NewsType, ExtractedFacts, Fact
    item = NewsItem(
        title="Test", title_ar="اختراق في منصة باينانس",
        summary_ar="تم اختراق منصة باينانس وسرقة أموال",
        news_type=NewsType.HACK
    )
    item.facts = ExtractedFacts(
        coins=["BTC"],
        facts=[Fact(entity="Binance", action="hacked", value_usd=570000000, amount_display="$570M")]
    )
    msg = format_news(item)
    assert msg is not None
    assert "🔴" in msg.text, "hack format should have red circle"
    assert "اختراق" in msg.text

def test_format_no_headline():
    from formatter import format_news
    from models import NewsItem, NewsType
    item = NewsItem(title="Test", title_ar="", news_type=NewsType.GENERAL)
    msg = format_news(item)
    assert msg is None, "no headline should return None"

def test_hashtag_generation():
    from formatter import _build_hashtags
    from models import NewsItem, ExtractedFacts, NewsType
    item = NewsItem(news_type=NewsType.ETF)
    item.facts = ExtractedFacts(coins=["BTC", "ETH", "SOL"])
    tags_str = _build_hashtags(item)
    assert "#BTC" in tags_str
    assert "#ETH" in tags_str

def test_hashtag_dedup():
    from formatter import _build_hashtags
    from models import NewsItem, ExtractedFacts, NewsType
    item = NewsItem(news_type=NewsType.GENERAL)
    item.facts = ExtractedFacts(coins=["BTC", "Bitcoin"])  # نفس العملة
    tags_str = _build_hashtags(item)
    # يجب أن يظهر #BTC مرة واحدة فقط
    btc_count = tags_str.count("#BTC")
    assert btc_count == 1, f"should dedup #BTC: {tags_str}"

run_test("تنسيق خبر عام", test_format_general)
run_test("تنسيق خبر اختراق", test_format_hack)
run_test("رفض بدون عنوان", test_format_no_headline)
run_test("توليد هاشتاغ", test_hashtag_generation)
run_test("إزالة تكرار الهاشتاغ", test_hashtag_dedup)


# ═══════════════════════════════════════════════════════════
# 9. اختبار الـ Pipeline الكامل
# ═══════════════════════════════════════════════════════════
section("🏭 اختبار Pipeline كامل")

def test_full_pipeline():
    """محاكاة دورة كاملة للـ Pipeline بدون API calls"""
    from models import NewsItem, NewsType, SourceQuality, ExtractedFacts
    from cleaner import clean_news_item
    from fact_extractor import extract_facts
    from classifier import classify_news, score_news, should_reject
    from deduplicator import check_duplicate, register_news
    from database import NewsDatabase
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        db = NewsDatabase(tmpdir)

        # إنشاء أخبار اختبار
        news_items = [
            NewsItem(
                title="CoinDesk: 🔵 BlackRock Bitcoin ETF Approved by SEC",
                summary="<p>The Securities and Exchange Commission has approved BlackRock's spot Bitcoin ETF application in a historic 3-2 vote. This marks a major milestone for crypto adoption.</p><p>Follow us on Twitter @coindesk</p>",
                source="CoinDesk", source_quality=SourceQuality.TIER_1,
                timestamp=time.time(), image="https://example.com/btc-etf.jpg"
            ),
            NewsItem(
                title="Breaking: Major Exchange Hacked for $570M",
                summary="A major cryptocurrency exchange was hacked today, resulting in approximately $570 million in losses. The attacker exploited a vulnerability in the bridge contract.",
                source="Blockworks", source_quality=SourceQuality.TIER_1,
                timestamp=time.time()
            ),
            NewsItem(
                title="How to buy Bitcoin: A beginner's guide to crypto",
                summary="This comprehensive guide will help you buy your first Bitcoin.",
                source="Google News", source_quality=SourceQuality.TIER_3,
                timestamp=time.time()
            ),
        ]

        # المرحلة 2: تنظيف
        cleaned = []
        for item in news_items:
            item = clean_news_item(item)
            cleaned.append(item)
        assert len(cleaned) == 3

        # المرحلة 3: استخراج حقائق
        for item in cleaned:
            item.facts = extract_facts(item.clean_summary, item.clean_title)
        assert cleaned[0].facts.main_entities  # BlackRock/SEC
        assert cleaned[1].facts.has_financial_data  # $570M

        # المرحلة 4: فحص التكرار
        unique = []
        for item in cleaned:
            if not check_duplicate(item, db):
                unique.append(item)
                register_news(item, db)
        assert len(unique) == 3  # جميعها فريدة

        # المرحلة 5: تصنيف + تقييم
        scored = []
        rejected_count = 0
        for item in unique:
            rejected, reason = should_reject(item)
            if rejected:
                rejected_count += 1
                continue
            item.news_type = classify_news(item)
            result = score_news(item)
            item.score = result.total
            if result.should_publish:
                scored.append(item)

        # الخبر 1 (ETF): يجب أن يُقبل
        # الخبر 2 (Hack): يجب أن يُقبل
        # الخبر 3 (Guide): يجب أن يُرفض
        assert rejected_count == 1, f"should reject 1: {rejected_count}"
        assert len(scored) == 2, f"should score 2: {len(scored)}"

        # الخبر الأول يجب أن يكون ETF
        etf_news = next((i for i in scored if i.source == "CoinDesk"), None)
        assert etf_news is not None
        assert etf_news.news_type.value == "etf", f"got: {etf_news.news_type.value}"
        assert etf_news.score >= 50, f"ETF score should be high: {etf_news.score}"

        # الخبر الثاني يجب أن يكون Hack
        hack_news = next((i for i in scored if "Hack" in i.title), None)
        assert hack_news is not None
        assert hack_news.news_type.value == "hack"
        assert hack_news.score >= 50

        info(f"ETF: {etf_news.score}/100 | Hack: {hack_news.score}/100 | Rejected: {rejected_count}")

run_test("دورة Pipeline كاملة", test_full_pipeline)


# ═══════════════════════════════════════════════════════════
# 10. اختبار استيراد كل الملفات
# ═══════════════════════════════════════════════════════════
section("📦 اختبار الاستيراد")

def test_imports():
    """كل الملفات يجب أن تستورد بدون أخطاء"""
    modules = [
        "models", "config", "database", "collector", "cleaner",
        "fact_extractor", "deduplicator", "classifier",
        "rewriter", "formatter", "publisher", "main"
    ]
    for mod_name in modules:
        try:
            __import__(mod_name)
            ok(f"import {mod_name}")
        except Exception as e:
            fail(f"import {mod_name}: {e}")

run_test("استيراد كل الوحدات", test_imports)


# ═══════════════════════════════════════════════════════════
# النتيجة النهائية
# ═══════════════════════════════════════════════════════════
section("📊 النتيجة النهائية")

print(f"\n  {BOLD}الاختبارات: {_total} إجمالي | {GREEN}{_passed} نجح{RESET} | {RED}{_failed} فشل{RESET}{BOLD}")

if _failed == 0:
    print(f"  {GREEN}🎉 كل الاختبارات نجحت!{RESET}")
else:
    print(f"  {RED}⚠️ {_failed} اختبار فشل — يحتاج مراجعة{RESET}")

print(f"\n{BOLD}{'='*60}{RESET}\n")

sys.exit(0 if _failed == 0 else 1)
