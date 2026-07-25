"""
🌐 Whale News Bot — ترجمة مبسّطة (Google Translate فقط)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ترجمة إنجليزي → عربي مع حماية أسماء الكيانات الكريبتوية.
"""

import os, re, hashlib, time, asyncio, json, threading
from typing import Optional, Tuple, Dict, List

import aiohttp

from config import log, BotConfig, COIN_MAP


# ═══════════════════════════════════════════════════════════
# خريطة عكسية: اسم العملة ← رمزها
# ═══════════════════════════════════════════════════════════
COIN_NAME_TO_TICKER = {}
for _kw, _sym in COIN_MAP.items():
    COIN_NAME_TO_TICKER[_kw.lower()] = _sym.upper()
for _kw in sorted(COIN_NAME_TO_TICKER, key=len, reverse=True):
    COIN_NAME_TO_TICKER[_kw] = COIN_NAME_TO_TICKER[_kw]


# ═══════════════════════════════════════════════════════════
# 💾 كاش الترجمة (ملف JSON)
# ═══════════════════════════════════════════════════════════
class TranslationCache:
    CACHE_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "translation_cache.json"
    )
    MAX_ENTRIES = 5000
    DEFAULT_TTL = 86400

    def __init__(self, ttl: int = None):
        self._memory: Dict[str, Dict] = {}
        self._ttl = ttl or self.DEFAULT_TTL
        self._lock = threading.Lock()
        self._dirty = False
        self._save_counter = 0
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = time.time()
                loaded = 0
                for key, entry in data.items():
                    if isinstance(entry, dict) and now - entry.get("timestamp", 0) < self._ttl * 2:
                        self._memory[key] = entry
                        loaded += 1
                if loaded:
                    log.info(f"💾 Translation cache: {loaded} entries loaded")
        except Exception as e:
            log.warning(f"Cache load error: {e}")

    def _save(self):
        try:
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, ensure_ascii=False, separators=(',', ':'))
        except Exception as e:
            log.warning(f"Cache save error: {e}")

    async def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key in self._memory:
                entry = self._memory[key]
                if time.time() - entry.get("timestamp", 0) < self._ttl:
                    return entry.get("result")
                del self._memory[key]
            return None

    async def set(self, key: str, value: str):
        with self._lock:
            self._memory[key] = {"result": value, "timestamp": time.time()}
            self._dirty = True
            self._save_counter += 1
            if len(self._memory) > self.MAX_ENTRIES:
                now = time.time()
                old = [k for k, v in self._memory.items()
                       if now - v.get("timestamp", 0) > self._ttl]
                for k in old:
                    del self._memory[k]
            if self._save_counter >= 20:
                self._save()
                self._save_counter = 0

    def flush(self):
        with self._lock:
            if self._dirty:
                self._save()
                self._dirty = False

    def hash_key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:12]


translation_cache = TranslationCache()


# ═══════════════════════════════════════════════════════════
# 🛡️ حماية أسماء الكيانات من الترجمة
# ═══════════════════════════════════════════════════════════
CRITICAL_NAMES = [
    "bitcoin", "btc", "ethereum", "eth", "ether", "solana", "sol", "xrp", "ripple",
    "cardano", "ada", "dogecoin", "doge", "avalanche", "avax", "polkadot", "dot",
    "chainlink", "link", "polygon", "matic", "litecoin", "ltc", "tron", "trx",
    "arbitrum", "arb", "optimism", "op", "aptos", "apt", "sui", "sei", "near",
    "uniswap", "aave", "binance", "coinbase", "kraken", "bybit", "okx", "kucoin",
    "blackrock", "microstrategy", "grayscale", "fidelity", "sec", "gensler",
    "satoshi", "vitalik", "saylor", "buterin", "cz", "musk", "dorsey",
    "usdt", "usdc", "tether", "dai", "defi", "nft", "web3", "dao", "etf",
    "ibit", "fbtc", "gbtc", "etha", "hodl",
    "fantom", "ftm", "cosmos", "atom", "stellar", "xlm", "hedera", "hbar",
    "shiba", "shib", "pepe", "toncoin", "ton", "near protocol",
]

GLOSSARY_AR = {
    "smart wallet": "المحفظة الذكية",
    "smart contract": "العقد الذكي",
    "multi-chain": "متعدد السلاسل",
    "cross-chain": "عبر السلاسل",
    "layer 2": "الطبقة الثانية",
    "layer 1": "الطبقة الأولى",
    "mainnet": "الشبكة الرئيسية",
    "testnet": "شبكة الاختبار",
    "bull market": "السوق الصاعد",
    "bear market": "السوق الهابط",
    "all-time high": "أعلى مستوى تاريخي",
    "all-time low": "أدنى مستوى تاريخي",
    "market cap": "القيمة السوقية",
    "open interest": "المركزيات المفتوحة",
    "funding rate": "سعر التمويل",
    "staking": "التحصيص",
    "mining": "التعدين",
    "halving": "التنصيف",
    "proof of stake": "إثبات الحصة",
    "proof of work": "إثبات العمل",
    "validator": "المُتحقق",
    "decentralized": "لامركزي",
    "inflows": "تدفقات داخلة",
    "outflows": "تدفقات خارجة",
    "hack": "اختراق",
    "exploit": "ثغرة أمنية",
    "stolen": "مُسروق",
    "rug pull": "احتيال",
    "surge": "قفزة",
    "plunge": "انهيار",
    "crash": "انهيار",
    "rally": "ارتفاع",
    "correction": "تصحيح",
    "liquidation": "تصفية",
    "leverage": "الرافعة المالية",
    "futures": "العقود الآجلة",
    "token unlock": "فك توكن",
    "token burn": "حرق توكن",
    "flash crash": "انهيار مفاجئ",
    "airdrop": "إيردروب",
    "roadmap": "خارطة الطريق",
    "launch": "إطلاق",
    "upgrade": "تحديث",
    "hard fork": "الانقسام الصلب",
    "soft fork": "الانقسام الناعم",
    "the merge": "الدمج",
}


def _protect_entities(text: str) -> Tuple[str, Dict[str, Tuple[str, Optional[str]]]]:
    """حماية الكيانات المهمة قبل الترجمة — نستبدلها بعلامات مؤقتة"""
    restore_map = {}
    protected = text
    counter = 0

    all_terms = []
    for term, trans in GLOSSARY_AR.items():
        all_terms.append((term, trans))
    for term in CRITICAL_NAMES:
        if term not in GLOSSARY_AR:
            all_terms.append((term, None))

    all_terms.sort(key=lambda x: len(x[0]), reverse=True)

    for term, trans in all_terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        matches = list(pattern.finditer(protected))
        if matches:
            for match in reversed(matches):
                placeholder = f"§§{counter:03d}§§"
                protected = protected[:match.start()] + placeholder + protected[match.end():]
                restore_map[placeholder] = (match.group(0), trans)
                counter += 1

    return protected, restore_map


def _restore_entities(text: str, restore_map: Dict) -> str:
    """استعادة الكيانات بعد الترجمة"""
    if not restore_map:
        return text

    result = text
    sorted_placeholders = sorted(restore_map.keys(), key=lambda x: int(x[2:5]), reverse=True)

    for placeholder in sorted_placeholders:
        original, trans = restore_map[placeholder]
        replacement = trans if trans else original

        num = int(placeholder[2:5])
        patterns = [
            re.escape(placeholder),
            re.escape(f"§§{num}§§"),
            re.escape(f"§ {num} §"),
            re.escape(f"({num})"),
            re.escape(f"[{num}]"),
            re.escape(f"«{num}»"),
        ]

        for pat in patterns:
            new_result = re.sub(pat, replacement, result, flags=re.IGNORECASE)
            if new_result != result:
                result = new_result
                break

    result = re.sub(r"§§\d{3}§§", "", result)
    return result


# ═══════════════════════════════════════════════════════════
# 🌐 Google Translate (الطريقة الوحيدة)
# ═══════════════════════════════════════════════════════════
async def google_translate(text: str) -> Optional[str]:
    """ترجمة نص إنجليزي → عربي مع حماية الأسماء"""
    if not text or len(text.strip()) < 3:
        return None

    try:
        protected_text, restore_map = _protect_entities(text)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": "en",
                    "tl": "ar",
                    "dt": "t",
                    "q": protected_text,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                translated_parts = []
                if data and isinstance(data, list) and len(data) > 0:
                    for item in data[0]:
                        if isinstance(item, list) and len(item) > 0:
                            translated_parts.append(item[0])

                result = "".join(translated_parts).strip()
                if not result or len(result) < 3:
                    return None

                result = _restore_entities(result, restore_map)
                return result
    except Exception as e:
        log.warning(f"Google Translate failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# 🏆 مدير الترجمة المبسّط
# ═══════════════════════════════════════════════════════════
class TranslationManager:
    """مدير ترجمة مبسّط — Google Translate فقط مع كاش"""

    def __init__(self, config: BotConfig):
        pass  # لا نحتاج API keys

    async def translate(self, text: str, force: bool = False) -> Optional[str]:
        """ترجمة نص — يُرجع نص عربي أو None"""
        if not text or len(text) < 3:
            return None

        # قص النص الطويل
        if len(text) > 1000:
            text = text[:1000]

        cache_key = translation_cache.hash_key(text)

        if not force:
            cached = await translation_cache.get(cache_key)
            if cached:
                log.info("💾 Cache hit")
                return cached

        result = await google_translate(text)
        if result:
            await translation_cache.set(cache_key, result)
            return result

        log.warning("Translation failed")
        return None

    async def translate_item(self, item) -> None:
        """ترجمة خبر — يملأ title_ar و summary_ar"""
        title = getattr(item, 'title', '') or ''
        summary = getattr(item, 'summary', '') or ''

        # ترجمة العنوان
        if title and not (item.lang == "ar"):
            item.title_ar = await self.translate(title) or title
        else:
            item.title_ar = title

        # ترجمة الملخص
        if summary and not (item.lang == "ar"):
            item.summary_ar = await self.translate(summary) or summary
        else:
            item.summary_ar = summary
