"""
🧪 Whale News Bot v2.0 - Tests
"""

import pytest, asyncio
from filters_v2 import NewsItem, NewsScorer, SemanticDeduplicator, filter_news_items
from translate_v2 import TranslationManager
from config_v2 import BotConfig


class TestNewsScorer:
    def test_score_breaking(self):
        scorer = NewsScorer()
        item = NewsItem(
            title="Bitcoin hacked: $50M stolen from exchange",
            link="https://example.com",
            summary="Major security breach",
            source="CoinDesk",
        )
        score, cats = scorer.score(item)
        assert score > 5.0
        assert "hack" in cats
        assert "breaking" in cats

    def test_score_normal(self):
        scorer = NewsScorer()
        item = NewsItem(
            title="Bitcoin price analysis today",
            link="https://example.com",
            summary="Technical analysis",
            source="CoinDesk",
        )
        score, cats = scorer.score(item)
        assert score < 3.0

    def test_extract_coins(self):
        scorer = NewsScorer()
        text = "Bitcoin and Ethereum surge while Solana drops"
        coins = scorer.extract_coins(text)
        assert "BTC" in coins
        assert "ETH" in coins
        assert "SOL" in coins


class TestDeduplicator:
    def test_duplicate_detection(self):
        dedup = SemanticDeduplicator(threshold=0.82)
        item1 = NewsItem(title="Bitcoin hits new all-time high", link="https://a.com")
        item2 = NewsItem(title="Bitcoin reaches new all-time high", link="https://b.com")

        assert not dedup.is_duplicate(item1)
        dedup.add(item1)
        assert dedup.is_duplicate(item2)

    def test_different_news(self):
        dedup = SemanticDeduplicator(threshold=0.82)
        item1 = NewsItem(title="Bitcoin hacked", link="https://a.com")
        item2 = NewsItem(title="Ethereum upgrade delayed", link="https://b.com")

        assert not dedup.is_duplicate(item1)
        dedup.add(item1)
        assert not dedup.is_duplicate(item2)


class TestFilterNews:
    def test_filter_spam(self):
        items = [
            NewsItem(title="Top 10 coins to buy now", link="https://spam.com"),
            NewsItem(title="Bitcoin exchange hacked", link="https://news.com"),
        ]
        filtered = filter_news_items(items, min_score=1.5)
        assert len(filtered) == 1
        assert "hacked" in filtered[0].title.lower()

    def test_filter_crypto_context(self):
        items = [
            NewsItem(title="Apple releases new iPhone", link="https://apple.com"),
            NewsItem(title="Bitcoin ETF approved by SEC", link="https://crypto.com"),
        ]
        filtered = filter_news_items(items, min_score=1.5)
        assert len(filtered) == 1
        assert "Bitcoin" in filtered[0].title


class TestTranslationCache:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        from translate_v2 import translation_cache
        await translation_cache.set("key1", "value1")
        result = await translation_cache.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_cache_miss(self):
        from translate_v2 import translation_cache
        result = await translation_cache.get("nonexistent")
        assert result is None


class TestBotConfig:
    def test_validation(self):
        config = BotConfig(TOKEN="", CHAT_ID="")
        errors = config.validate()
        assert len(errors) == 2
        assert "TELEGRAM_BOT_TOKEN" in errors[0]

    def test_valid_config(self):
        config = BotConfig(TOKEN="test_token", CHAT_ID="123456")
        errors = config.validate()
        assert len(errors) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
