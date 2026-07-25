"""
🤖 Whale News Bot — Telegram Bot (مبسّط)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
بوت مبسّط: جلب → ترجمة → تنسيق → إرسال.
"""

import os, re, time, json, asyncio, hashlib
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

import aiohttp
from aiohttp import ClientTimeout

from config import (
    log, BotConfig, BotState, TELEGRAM_RATE_LIMITER,
    MAX_NEWS_PER_SCAN, MAX_NEWS_AGE, SCAN_INTERVAL, tz,
    save_sent_news, sent_news_hashes,
)
from filters import NewsItem, filter_news_items
from rss import fetch_all_news, fetch_etf_flows, session_manager
from translate import TranslationManager, translation_cache, COIN_NAME_TO_TICKER


# ═══════════════════════════════════════════════════════════
# 📤 Message Queue
# ═══════════════════════════════════════════════════════════
@dataclass
class QueuedMessage:
    text: str
    image_url: Optional[str] = None
    chat_id: Optional[str] = None
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3


class MessageQueue:
    def __init__(self):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._processed: Set[str] = set()
        self._stats = {"sent": 0, "failed": 0}

    async def put(self, msg: QueuedMessage):
        await self._queue.put((-msg.priority, time.time(), msg))

    async def get(self) -> Optional[QueuedMessage]:
        try:
            _, _, msg = await asyncio.wait_for(self._queue.get(), timeout=5)
            return msg
        except asyncio.TimeoutError:
            return None

    async def process(self):
        while True:
            msg = await self.get()
            if msg:
                await _send_telegram(msg)


message_queue = MessageQueue()


# ═══════════════════════════════════════════════════════════
# 📨 إرسال Telegram
# ═══════════════════════════════════════════════════════════
async def _send_telegram(msg: QueuedMessage):
    """إرسال رسالة إلى تيليجرام"""
    if not msg.text:
        return

    chat_id = msg.chat_id or config.CHAT_ID
    max_msg_len = 4096

    # تقسيم الرسائل الطويلة
    text = msg.text[:max_msg_len]

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }

    # إرسال الصورة مع النص
    if msg.image_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(msg.image_url, timeout=ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        img_data = await resp.read()
                        # إرسال كصورة
                        img_payload = {
                            "chat_id": chat_id,
                            "photo": aiohttp.payload.BytesPayload(img_data, content_type="image/jpeg"),
                            "caption": text[:1024],
                            "parse_mode": "HTML",
                        }
                        async with session.post(
                            f"https://api.telegram.org/bot{config.TOKEN}/sendPhoto",
                            data=img_payload,
                            timeout=ClientTimeout(total=30),
                        ) as resp:
                            if resp.status == 200:
                                message_queue._stats["sent"] += 1
                                log.info(f"✅ Sent (photo) to {chat_id}")
                                return
        except Exception as e:
            log.warning(f"Photo send failed: {e}")

    # إرسال كنص
    await TELEGRAM_RATE_LIMITER.acquire()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{config.TOKEN}/sendMessage",
                json=payload,
                timeout=ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    message_queue._stats["sent"] += 1
                    log.info(f"✅ Sent to {chat_id}")
                else:
                    error = await resp.text()
                    log.warning(f"❌ Send failed: {resp.status} {error[:200]}")
                    message_queue._stats["failed"] += 1
    except Exception as e:
        log.warning(f"Send error: {e}")
        message_queue._stats["failed"] += 1


# ═══════════════════════════════════════════════════════════
# 🧹 تنظيف بسيط قبل الإرسال
# ═══════════════════════════════════════════════════════════
def clean_message(text: str) -> Optional[str]:
    """تنظيف بسيط: كشف الترجمة الفاسدة + إبقاء التوقيع
    — تنظيف الكلمات المدمجة بدل حظر الرسالة كلها
    — السماح بالكلمات الإنجليزية الشائعة في سياق الأخبار
    """
    if not text or not text.strip():
        return None

    lines = text.strip().split("\n")
    cleaned = []
    signature_found = False

    # أسماء إنجليزية مسموحة — قائمة واسعة جداً
    _allowed = {
        # عملات رئيسية
        "Bitcoin", "Ethereum", "Solana", "Binance", "Coinbase", "USDT", "USDC",
        "BlackRock", "MicroStrategy", "Grayscale", "Fidelity", "SEC", "ETF",
        "DeFi", "NFT", "Web3", "Litecoin", "Dogecoin", "Avalanche", "Polkadot",
        "Chainlink", "Polygon", "Tron", "Uniswap", "Aptos", "Arbitrum",
        "Optimism", "Stellar", "Hedera", "Cosmos", "Fantom", "Aave", "Tether",
        "Circle", "OKX", "Kraken", "Bybit", "Ripple", "Cardano", "Toncoin",
        "Near", "Sui", "Sei", "Shiba", "Pepe", "Vitalik", "Satoshi", "Saylor",
        "Gensler", "CZ", "Dorsey", "Buterin", "Musk",
        "BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX", "DOT",
        "LINK", "POL", "LTC", "TRX", "UNI", "APT", "ARB", "SUI", "SEI",
        "TON", "FTM", "ATOM", "XLM", "HBAR", "SHIB", "PEPE", "DAI", "OP",
        "IBIT", "FBTC", "GBTC", "ETHA", "HODL", "NEAR",
        # عملات إضافية
        "Monero", "Tezos", "VeChain", "Filecoin", "Zcash", "EOS",
        "Algorand", "Kaspa", "Worldcoin", "Injective", "Render",
        "Jupiter", "Raydium", "Drift", "Hyperliquid", "EigenLayer",
        "Ondo", "Berachain", "Bittensor", "Bonk", "Floki",
        "BOME", "Pengu", "WIF", "Virtuals", "AI16z",
        "Celestia", "Starknet", "Manta", "Linea", "Mantle", "Scroll",
        "Maker", "Lido", "Curve", "Synthetix", "Compound", "GMX", "dYdX",
        "Pendle", "Jito", "EtherFi", "Renzo", "Morpho", "Aerodrome",
        "Decentraland", "Sandbox", "Axie", "Graph", "Helium",
        "XMR", "XTZ", "VET", "FIL", "ZEC", "ALGO", "ICP", "KAS", "WLD",
        "STRK", "TIA", "INJ", "RENDER", "FET", "RUNE", "JUP", "RAY",
        "HYPE", "EIGEN", "ETHFI", "REZ", "AERO", "TAO",
        "MANA", "SAND", "AXS", "GRT", "HNT", "MKR", "CRV", "SNX", "COMP",
        # بروتوكولات ومنصات
        "Wormhole", "LayerZero", "Stargate", "OpenSea", "Blur",
        "MetaMask", "Ledger", "Trezor", "Trust",
        "Bitfinex", "Bitstamp", "Gemini", "Bitget", "MEXC", "Deribit",
        "Sushi", "Pancake", "Curve", "Balancer", "Rocket",
        "Pyth", "Band", "Akash", "Fetch",
        "CoinDesk", "CoinTelegraph", "Decrypt", "BeInCrypto", "Coinpedia",
        "Blockworks", "Bitcoinist",
        # ETF tickers
        "EZET", "BITB", "BITX", "ARKB", "BTCO", "BITQ", "BKCH",
        "VanEck", "Invesco", "Bitwise", "WisdomTree", "ProShares",
        "CoinShares", "Galaxy", "HashDex", "Paxos",
        "Spot", "Bitcoin", "Ethereum", "Solana",
        # منظمين وشخصيات
        "Powell", "Yellen", "FOMC", "FTX", "SBF",
        "Armstrong", "Garlinghouse", "Silbert", "Winklevoss",
        "Nakamoto", "Hayden", "Stani", "Gavin", "Charles",
        "Federal", "Reserve", "Treasury", "CFTC",
        "PayPal", "Visa", "Mastercard",
        # مستكشفات وأدوات
        "Etherscan", "BscScan", "Solscan", "DexScreener", "DexTools",
        "CoinGecko", "CoinMarketCap", "TradingView", "Glassnode",
        "Nansen", "Dune", "Arkham", "Whale", "DeFiLlama",
        "Lookonchain", "Bubblemaps",
        # مصطلحات تقنية
        "mainnet", "testnet", "staking", "mining", "halving", "restaking",
        "DePIN", "GameFi", "SocialFi", "RWA",
        "rollup", "zkSync", "zk",
        "memecoin", "stablecoin", "altcoin",
        "airdrop", "token", "tokens", "coins",
        "blockchain", "crypto", "cryptocurrency", "cryptocurrencies",
        "hack", "exploit", "vulnerability",
        "inflows", "outflows", "whales",
        "liquidation", "leverage", "futures",
        "liquidity", "yield", "farming",
        "launch", "upgrade", "fork", "roadmap",
        "audit", "sanction", "compliance",
        "CBDC", "ETF", "ETFs", "NFTs", "DAO",
        "DAOs", "DEX", "CEX", "FOMO", "FUD",
        "REKT", "WAGMI", "LAMBO",
        "bullish", "bearish", "rally", "crash", "surge", "plunge",
        "correction", "breakout", "consolidation",
        "support", "resistance", "volume",
        "market", "price", "trading", "investors", "traders",
        "analysts", "experts", "regulators",
        "inflation", "deflation", "recession",
        "interest", "rate", "monetary",
        "launchpad", "presale", "minting",
        "partnership", "integration", "ecosystem", "network",
        "protocol", "platform", "project", "community",
        "announcement", "report", "analysis",
        "approved", "rejected", "banned", "regulated",
        "investigation", "lawsuit", "settlement",
        "significant", "substantial", "notable", "massive",
        "expected", "anticipated", "scheduled",
        "record", "milestone", "benchmark",
        "weekly", "monthly", "quarterly",
        "bull", "bear", "pump", "dump",
        "long", "short", "position",
        "smart", "contract", "wallet",
        "gas", "fee", "fees", "hash", "nonce",
        "node", "nodes", "block", "blocks",
        "proof", "consensus", "validator",
        "bridge", "bridges", "oracle", "oracles",
        "wrapped", "WBTC", "WETH", "LSD", "LRT", "LST",
        "FOMC", "CPI", "GDP", "NASDAQ", "DXY",
        "Bitmain", "Antminer", "Marathon", "Riot",
        "Foundry", "Mining", "Pool", "Antpool",
        "Convex", "Tokemak", "Bancor", "Numeraire",
        "Radix", "Aleph", "Neon", "Zeta", "Kinto", "Lumia",
        "Morpheus", "Ritual", "Arc",
        "Stablecoins", "Altcoins", "Cryptocurrencies",
        "DeFi", "RWA", "AI", "GPU",
        "Firedancer", "Solayer", "Sanctum", "Marinade",
        "Fragment", "Bond", "Solv", "Berkshire",
        "Strategy",
        # ── كلمات إنجليزية شائعة في الأخبار ──
        "after", "before", "during", "while", "since", "until",
        "with", "from", "into", "onto", "upon", "over", "under", "above",
        "about", "against", "between", "through", "without", "within",
        "also", "just", "only", "very", "still", "even", "back", "down",
        "more", "most", "less", "much", "well", "then", "than", "that",
        "this", "these", "those", "each", "every", "some", "such", "many",
        "been", "were", "have", "will", "would", "could", "should",
        "does", "done", "goes", "went", "come", "came", "made", "took",
        "said", "says", "told", "asks", "wants", "needs", "uses",
        "first", "last", "next", "recent", "latest", "earliest",
        "year", "years", "month", "months", "week", "weeks", "days",
        "today", "yesterday", "time", "times",
        "data", "numbers", "figure", "figures", "level", "levels",
        "high", "highs", "lows", "peak", "peaks", "bottom",
        "drop", "drops", "rise", "rises", "fall", "falls",
        "gain", "gains", "loss", "losses", "profit", "profits",
        "fund", "funds", "capital", "revenue", "asset", "assets",
        "firm", "company", "companies", "group", "industry", "sector",
        "user", "users", "client", "clients", "share", "shares",
        "plan", "plans", "rule", "rules", "law", "laws",
        "court", "judge", "case", "action", "actions",
        "city", "state", "country", "region", "global", "world", "north", "south",
        "east", "west", "asia", "europe", "america", "africa",
        "bank", "banks", "finance", "financial", "economy", "economic",
        "bill", "billion", "million", "thousand", "percent",
        "government", "political", "policy", "public", "private",
        "tech", "technology", "digital", "internet", "software", "system",
        "chief", "executive", "director", "founder", "leader",
        "news", "media", "press", "blog", "social",
        "risk", "risks", "threat", "threats", "concern", "impact",
        "growth", "decline", "increase", "decrease",
        "change", "changes", "move", "moves", "shift", "turn",
        "ahead", "behind", "close", "open", "near", "far",
        "strong", "weak", "fast", "slow", "sharp", "steady",
        "area", "space", "field", "range", "zone",
        "effort", "push", "pull", "force", "power",
        "role", "part", "step", "stage", "phase",
        "base", "core", "key", "major", "minor",
        "deal", "offer", "trade", "sales", "buy", "sell",
        "hold", "keep", "give", "take", "send",
        "show", "shows", "point", "points",
        "likely", "unlikely", "possible", "sure",
        "real", "true", "false", "clear",
        "great", "huge", "tiny", "small", "large",
        "four", "three", "five", "eight", "nine",
        "half", "double", "single", "total",
        "according", "following", "including", "despite",
        "however", "although", "therefore", "because",
        "recently", "reported", "announced", "revealed",
        "confirmed", "stated", "noted", "added",
        "remains", "continues", "reached", "hit",
        "passed", "crossed", "surpassed", "exceeded",
        "breaks", "hits", "sets", "gets",
        "reuters", "associated", "press",
    }

    for line in lines:
        stripped = line.strip()

        # سطر فارغ
        if not stripped:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        # سطر التوقيع — نحتفظ به مرة واحدة فقط
        if "@newscrypto1m" in stripped:
            if not signature_found:
                cleaned.append(stripped)
                signature_found = True
            continue

        # سطر هاشتاغات — نحتفظ به
        if re.match(r'^#', stripped):
            cleaned.append(stripped)
            continue

        # (1) سكريبتات خاطئة (Telugu, Devanagari...)
        if re.search(r'[\u0C00-\u0C7F\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0E00-\u0E7F]', stripped):
            log.warning(f"🧹 Blocked: wrong Unicode script")
            return None

        # (2) كلمات مدمجة عربي + إنجليزي = تنظيفها بدل حظرها
        cleaned_words = []
        words = stripped.split()
        for word in words:
            # تجاهل الهاشتاغات والرموز
            if word.startswith('#') or word.startswith('@') or word.startswith('http'):
                cleaned_words.append(word)
                continue
            # تنظيف علامات الترقيم من الكلمة للفحص
            bare = word.strip('.,!?;:()-[]{}"\'').strip()
            word_has_arabic = bool(re.search(r'[\u0600-\u06FF]', bare))
            word_has_latin = bool(re.search(r'[a-zA-Z]', bare))
            if word_has_arabic and word_has_latin:
                # كلمة مدمجة — احتفظ بالجزء العربي فقط
                arabic_part = re.sub(r'[a-zA-Z]+', '', bare)
                if len(arabic_part) >= 2:
                    cleaned_words.append(arabic_part)
                log.info(f"🧹 Cleaned corrupted word: '{word}' → '{arabic_part}'")
                continue
            cleaned_words.append(word)

        stripped = " ".join(cleaned_words)
        if not stripped:
            continue

        # (3) كلمات إنجليزية مشبوهة — نسامح بـ 2 كلمة فقط
        english_words = re.findall(r'\b([a-zA-Z]{3,})\b', stripped)
        suspicious = [w for w in english_words if w not in _allowed]
        if len(suspicious) > 2:
            log.info(f"🧹 Removed line with {len(suspicious)} unknown English: {suspicious[:5]}")
            continue
        if suspicious:
            log.info(f"🧹 Allowed line with {len(suspicious)} unknown English: {suspicious}")

        cleaned.append(stripped)

    if not cleaned:
        return None

    result = "\n".join(cleaned).strip()

    # فحص أدنى: يجب أن يكون فيه عربي
    arabic_chars = sum(1 for c in result if '\u0600' <= c <= '\u06FF')
    if arabic_chars < 5:
        return None

    return result if len(result) > 10 else None


# ═══════════════════════════════════════════════════════════
# 📝 تنسيق الخبر
# ═══════════════════════════════════════════════════════════
def format_news_item(item: NewsItem) -> Optional[str]:
    """تنسيق الخبر: عنوان فقط + هاشتاغات + توقيع"""
    title_ar = item.title_ar or item.title

    if not title_ar or title_ar == item.title:
        return None

    # التأكد أن العنوان ينتهي بنقطة
    title_clean = title_ar.strip()
    if title_clean and title_clean[-1] not in ".؟!؟.؟\u06d4":
        title_clean += "."

    # رمز بسيط
    msg = f"🔵 {title_clean}"

    # إضافة العملات
    if item.coins:
        seen = set()
        unique = []
        for c in item.coins:
            canonical = COIN_NAME_TO_TICKER.get(c.lower(), c.upper())
            if canonical not in seen:
                seen.add(canonical)
                unique.append(canonical)
        if unique:
            coins_str = " ".join([f"#{c}" for c in unique[:5]])
            msg += f"\n\n{coins_str}"

    msg += "\n\n✉️ @newscrypto1m"
    return msg


def format_etf_flows(etf_data: Dict) -> str:
    """تنسيق بيانات ETF"""
    from config import tz
    msg = "📊 تدفقات صناديق ETF\n"

    btc_total = etf_data.get("btc_total", 0)
    btc_dir = "إيجابي" if btc_total > 0 else ("سلبي" if btc_total < 0 else "تعادل")
    btc_sign = "+" if btc_total > 0 else ""
    msg += f"🔴 Bitcoin ETF — {btc_dir} {btc_sign}{btc_total:.1f}M\n"

    eth_total = etf_data.get("eth_total", 0)
    eth_dir = "إيجابي" if eth_total > 0 else ("سلبي" if eth_total < 0 else "تعادل")
    eth_sign = "+" if eth_total > 0 else ""
    msg += f"🔵 Ethereum ETF — {eth_dir} {eth_sign}{eth_total:.1f}M"

    msg += "\n\n✉️ @newscrypto1m"
    return msg


# ═══════════════════════════════════════════════════════════
# 🔍 حلقة فحص الأخبار
# ═══════════════════════════════════════════════════════════
async def scan_news_loop(config: BotConfig, state: BotState, translator: TranslationManager):
    """حلقة جلب ونشر الأخبار"""
    log.info("🔍 News scanner started")
    await asyncio.sleep(10)

    while True:
        try:
            if state.bot_shutdown or not state.auto_alerts_enabled:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            log.info("🔍 Scanning news...")

            # جلب الأخبار
            news = await fetch_all_news(max_concurrent=5)
            if not news:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # فلترة
            filtered = filter_news_items(news)

            now = time.time()
            alerts_sent = 0

            for item in filtered[:MAX_NEWS_PER_SCAN]:
                # فحص العمر
                if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
                    sent_news_hashes.add(item.hash)
                    continue

                # فحص الإرسال السابق
                if item.hash in sent_news_hashes:
                    continue

                # فحص cooldown
                if item.hash in state.last_alerts_hashes:
                    if now - state.last_alerts_hashes[item.hash] < 21600:
                        continue

                # ترجمة
                await translator.translate_item(item)
                if not item.title_ar:
                    log.debug(f"  ⏭️ No translation: {item.title[:60]}")
                    continue

                # تنسيق
                msg = format_news_item(item)
                if not msg:
                    log.debug(f"  ⏭️ No format: {item.title_ar[:60]}")
                    continue

                # تنظيف بسيط — كشف الترجمة الفاسدة
                msg = clean_message(msg)
                if not msg:
                    log.info(f"  🧹 Cleaned out: {item.title[:60]}")
                    continue

                # منع التكرار بعد الترجمة (نفس الخبر من مصدرين مختلفين)
                title_ar_hash = hashlib.md5(item.title_ar.encode()).hexdigest()[:12]
                if title_ar_hash in sent_news_hashes:
                    log.info(f"🧹 Duplicate after translation: {item.title[:60]}")
                    continue

                # إرسال
                sent_news_hashes.add(item.hash)
                sent_news_hashes.add(title_ar_hash)
                state.last_alerts_hashes[item.hash] = now

                # للقناة
                if state.is_channel_enabled(config):
                    await message_queue.put(QueuedMessage(
                        text=msg, image_url=item.image, chat_id=config.CHANNEL_ID, priority=2,
                    ))

                # للمالك
                await message_queue.put(QueuedMessage(
                    text=msg, image_url=item.image, chat_id=config.CHAT_ID, priority=2,
                ))

                alerts_sent += 1
                log.info(f"  ✉️ {item.title[:60]}")

            log.info(f"📊 Scan: {len(news)} fetched, {len(filtered)} filtered, {alerts_sent} sent")

            # حفظ الهاشات
            if alerts_sent > 0:
                save_sent_news()

            # ETF flows
            try:
                etf = await fetch_etf_flows()
                if etf:
                    etf_hash = f"etf_{etf['date']}"
                    if etf_hash not in sent_news_hashes:
                        sent_news_hashes.add(etf_hash)
                        msg = format_etf_flows(etf)
                        if state.is_channel_enabled(config):
                            await message_queue.put(QueuedMessage(text=msg, chat_id=config.CHANNEL_ID, priority=1))
                        await message_queue.put(QueuedMessage(text=msg, chat_id=config.CHAT_ID, priority=1))
            except Exception as e:
                log.warning(f"ETF flows error: {e}")

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            log.error(f"Scan loop error: {e}")
            await asyncio.sleep(60)


# ═══════════════════════════════════════════════════════════
# 🤖 أوامر البوت
# ═══════════════════════════════════════════════════════════
async def handle_command(text: str, chat_id: str) -> Optional[str]:
    """معالجة الأوامر"""
    text = text.strip()

    if text == "/start":
        return ("🤖 Whale News Bot\n\n"
                "أبسط بوت أخبار كريبتو.\n"
                "يُترجم الأخبار بالعربي ويُرسلها تلقائياً.\n\n"
                "الأوامر:\n"
                "/status — حالة البوت\n"
                "/pause — إيقاف مؤقت\n"
                "/resume — استئناف\n"
                "/stats — إحصائيات")

    elif text == "/status":
        enabled = "✅ يعمل" if config.state.auto_alerts_enabled else "⏸️ متوقف"
        channel = "✅" if config.state.is_channel_enabled(config) else "❌"
        return (f"📊 حالة البوت\n\n"
                f"الحالة: {enabled}\n"
                f"القناة: {channel}\n"
                f"المصادر: {len(NEWS_SOURCES)}\n"
                f"المُرسلة: {len(sent_news_hashes)}")

    elif text == "/pause":
        config.state.auto_alerts_enabled = False
        return "⏸️ تم الإيقاف المؤقت."

    elif text == "/resume":
        config.state.auto_alerts_enabled = True
        return "✅ تم الاستئناف."

    elif text == "/stats":
        return (f"📊 الإحصائيات\n\n"
                f"المُرسلة: {len(sent_news_hashes)}\n"
                f"الحالة: {'يعمل' if config.state.auto_alerts_enabled else 'متوقف'}")

    return None


# ═══════════════════════════════════════════════════════════
# 🚀 تشغيل البوت
# ═══════════════════════════════════════════════════════════
async def run_bot(config: BotConfig, state: BotState):
    """تشغيل البوت الدائم"""
    translator = TranslationManager(config)

    # تحميل الأخبار المُرسلة
    from config import load_sent_news
    load_sent_news()
    state.sent_news_hashes = sent_news_hashes

    # بدء حلقة الفحص
    asyncio.create_task(scan_news_loop(config, state, translator))
    asyncio.create_task(message_queue.process())

    # Polling
    offset = 0
    log.info("🤖 Bot started (polling)")

    while not state.bot_shutdown:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.telegram.org/bot{config.TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                    timeout=ClientTimeout(total=35),
                ) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(5)
                        continue

                    data = await resp.json()
                    if not data.get("ok"):
                        await asyncio.sleep(5)
                        continue

                    for update in data.get("result", []):
                        offset = update.get("update_id", 0) + 1
                        message = update.get("message", {})
                        text = message.get("text", "")
                        chat_id = str(message.get("chat", {}).get("id", ""))

                        if text.startswith("/"):
                            reply = await handle_command(text, chat_id)
                            if reply:
                                await TELEGRAM_RATE_LIMITER.acquire()
                                try:
                                    await session.post(
                                        f"https://api.telegram.org/bot{config.TOKEN}/sendMessage",
                                        json={"chat_id": chat_id, "text": reply},
                                        timeout=ClientTimeout(total=10),
                                    )
                                except Exception:
                                    pass
        except Exception as e:
            log.warning(f"Polling error: {e}")
            await asyncio.sleep(10)

    # تنظيف
    await session_manager.close()


async def run_oneshot(config: BotConfig, state: BotState):
    """تشغيل دورة واحدة (GitHub Actions)"""
    log.info("🎯 Oneshot mode")

    translator = TranslationManager(config)

    # تحميل الأخبار المُرسلة
    from config import load_sent_news
    load_sent_news()
    state.sent_news_hashes = sent_news_hashes

    # جلب
    news = await fetch_all_news(max_concurrent=5)
    filtered = filter_news_items(news)

    now = time.time()
    alerts_sent = 0

    for item in filtered[:MAX_NEWS_PER_SCAN]:
        if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
            sent_news_hashes.add(item.hash)
            continue
        if item.hash in sent_news_hashes:
            continue

        await translator.translate_item(item)
        if not item.title_ar:
            log.debug(f"  ⏭️ No translation: {item.title[:60]}")
            continue

        msg = format_news_item(item)
        if not msg:
            log.debug(f"  ⏭️ No format: {item.title_ar[:60]}")
            continue

        msg = clean_message(msg)
        if not msg:
            log.info(f"  🧹 Cleaned out: {item.title[:60]}")
            continue

        # منع التكرار بعد الترجمة
        title_ar_hash = hashlib.md5(item.title_ar.encode()).hexdigest()[:12]
        if title_ar_hash in sent_news_hashes:
            continue

        sent_news_hashes.add(item.hash)
        sent_news_hashes.add(title_ar_hash)

        if state.is_channel_enabled(config):
            await message_queue.put(QueuedMessage(text=msg, image_url=item.image, chat_id=config.CHANNEL_ID))
        await message_queue.put(QueuedMessage(text=msg, image_url=item.image, chat_id=config.CHAT_ID))

        alerts_sent += 1
        log.info(f"  ✉️ {item.title[:60]}")

    # معالجة الطابور
    for _ in range(50):
        msg = await message_queue.get()
        if msg:
            await _send_telegram(msg)

    if alerts_sent > 0:
        save_sent_news()

    log.info(f"📊 Oneshot: {len(news)} fetched, {len(filtered)} filtered, {alerts_sent} sent")
    await session_manager.close()


# ═══ للتوافق مع handle_command
from config import NEWS_SOURCES, config
