"""
🌐 Whale News Bot v2.0 - نظام الترجمة المتقدم (مُحسّن)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ترجمة async مع persistent caching، verification، و fallback متعدد

التغييرات v2.1:
- System Prompt مُصغّر (~100 سطر بدل ~170)
- مكالمة Gemini واحدة بدل اثنتين (توفير 50% من التكلفة)
- Cache دائم (ملف JSON) بدل ذاكرة فقط
- _parse_output() نظيف — JSON فقط بدون dead code
- translate_item() يملأ news_format و importance مباشرة
"""

import os, re, hashlib, time, asyncio, json, threading
from typing import Optional, Tuple, Dict, List

import aiohttp

from config import log, BotConfig, COIN_MAP


from source_quality import source_quality


# ═══════════════════════════════════════════════════════════
# 🔗 خريطة عكسية: اسم العملة ← رمزها (لمنع التكرار)
# ═══════════════════════════════════════════════════════════
COIN_NAME_TO_TICKER = {}
for _kw, _sym in COIN_MAP.items():
    COIN_NAME_TO_TICKER[_kw.lower()] = _sym.upper()
# إزالة التعارضات: احتفظ بالأطول أولاً
for _kw in sorted(COIN_NAME_TO_TICKER, key=len, reverse=True):
    COIN_NAME_TO_TICKER[_kw] = COIN_NAME_TO_TICKER[_kw]


# ═══════════════════════════════════════════════════════════
# 💾 Persistent Translation Cache (ملف JSON + ذاكرة مؤقتة)
# ═══════════════════════════════════════════════════════════
class TranslationCache:
    """ذاكرة ترجمة دائمة — تحفظ في ملف JSON وتحمل عند البدء"""

    CACHE_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "translation_cache.json"
    )
    MAX_ENTRIES = 5000
    DEFAULT_TTL = 86400  # 24 ساعة

    def __init__(self, ttl: int = None):
        self._memory: Dict[str, Dict] = {}
        self._ttl = ttl or self.DEFAULT_TTL
        self._lock = threading.Lock()
        self._dirty = False
        self._save_counter = 0
        self._load()

    def _load(self):
        """تحميل الكاش من الملف عند البدء"""
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
                log.info(f"💾 Translation cache: {loaded} entries loaded from disk")
        except Exception as e:
            log.warning(f"Cache load error: {e}")

    def _save(self):
        """حفظ الكاش في الملف"""
        try:
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, ensure_ascii=False, separators=(',', ':'))
        except Exception as e:
            log.warning(f"Cache save error: {e}")

    async def get(self, key: str) -> Optional[Dict]:
        with self._lock:
            if key in self._memory:
                entry = self._memory[key]
                if time.time() - entry.get("timestamp", 0) < self._ttl:
                    return entry.get("result")
                del self._memory[key]
                self._dirty = True
            return None

    async def set(self, key: str, value: Dict):
        with self._lock:
            self._memory[key] = {"result": value, "timestamp": time.time()}
            self._dirty = True
            self._save_counter += 1

            # تنظيف القديم
            if len(self._memory) > self.MAX_ENTRIES:
                now = time.time()
                old = [k for k, v in self._memory.items()
                       if now - v.get("timestamp", 0) > self._ttl]
                for k in old:
                    del self._memory[k]

            # حفظ تلقائي كل 20 إضافة
            if self._save_counter >= 20:
                self._save()
                self._save_counter = 0

    def flush(self):
        """حفظ فوري للكاش — متزامن، آمن الاستدعاء من finally"""
        with self._lock:
            if self._dirty:
                self._save()
                self._dirty = False

    def _hash_key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:12]


translation_cache = TranslationCache()


# ═══════════════════════════════════════════════════════════
# 🛡️ Entity Protection
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
    "user experience": "تجربة المستخدم",
    "verification": "التحقق",
    "upgrade": "تحديث",
    "launch": "إطلاق",
    "release": "إصدار",
    "roadmap": "خارطة الطريق",
    "airdrop": "إيردروب",
    "staking": "التحصيص",
    "mining": "التعدين",
    "halving": "التنصيف",
    "hard fork": "الانقسام الصلب",
    "soft fork": "الانقسام الناعم",
    "the merge": "الدمج",
    "proof of stake": "إثبات الحصة",
    "proof of work": "إثبات العمل",
    "validator": "المُتحقق",
    "decentralized": "لامركزي",
    "decentralization": "اللامركزية",
    "institutional": "مؤسسي",
    "inflows": "تدفقات داخلة",
    "outflows": "تدفقات خارجة",
    "hack": "اختراق",
    "exploit": "ثغرة أمنية",
    "stolen": "مُسروق",
    "drained": "تم تصريفه",
    "rug pull": "احتيال",
    "breach": "اختراق أمني",
    "vulnerability": "ثغرة",
    "phishing": "تصيد",
    "surge": "قفزة",
    "plunge": "انهيار",
    "crash": "انهيار",
    "rally": "ارتفاع",
    "correction": "تصحيح",
    "dump": "هبوط حاد",
    "pump": "ضخ",
    "liquidation": "تصفية",
    "leverage": "الرافعة المالية",
    "futures": "العقود الآجلة",
    "token unlock": "فك توكن",
    "token burn": "حرق توكن",
    "buyback and burn": "إعادة الشراء والحرق",
    "flash crash": "انهيار مفاجئ",
    "massive sell-off": "بيع جماعي",
    "capitulation": "استسلام",
}


def _protect_entities(text: str) -> Tuple[str, Dict[str, Tuple[str, Optional[str]]]]:
    """حماية الكيانات المهمة قبل الترجمة"""
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
            for match in reversed(matches):  # من الآخر للحفاظ على المواقع
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
# 🧹 News Pre-Cleaning (before Gemini processing)
# ═══════════════════════════════════════════════════════════

BAD_LINES = [
    "read more",
    "first appeared",
    "originally published",
    "source:",
    "via ",
    "✉️",
]


def _normalize_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_duplicate(a: str, b: str) -> bool:
    a = _normalize_text(a).lower()
    b = _normalize_text(b).lower()
    if a == b:
        return True
    if len(a) > 20 and a in b:
        return True
    if len(b) > 20 and b in a:
        return True
    return False


def clean_news(raw: str) -> str:
    """Clean raw crypto news before sending it to Gemini.

    Removes: duplicates, RSS artifacts, bad hashtags, channel signature.
    Keeps: one headline, one hashtag max, deduplicated body.
    """
    if not raw:
        return ""

    raw = raw.replace("\r", "")
    lines = [x.strip() for x in raw.split("\n") if x.strip()]

    result = []
    hashtags = []
    headline = None

    for line in lines:
        low = line.lower()

        # حذف توقيع القناة
        if "@newscrypto1m" in low:
            continue

        # حذف أسطر RSS
        if any(x in low for x in BAD_LINES):
            continue

        # جمع الهاشتاغات
        if line.startswith("#"):
            tag = line.lower()
            if tag not in hashtags:
                hashtags.append(line)
            continue

        # أول عنوان
        if headline is None and line.startswith("🔵"):
            headline = line
            result.append(line)
            continue

        # حذف تكرار العنوان
        if headline:
            h = headline.replace("🔵", "").strip()
            if _is_duplicate(h, line):
                continue

        # حذف تكرار أي سطر
        duplicated = False
        for old in result:
            if _is_duplicate(old, line):
                duplicated = True
                break
        if duplicated:
            continue

        result.append(line)

    # إضافة هاشتاغ واحد فقط
    if hashtags:
        result.append("")
        result.append(hashtags[0])

    return "\n".join(result)


# ═══════════════════════════════════════════════════════════
# 🤖 System Prompt — المحرر الرئيسي (مُصغّر)
# ═══════════════════════════════════════════════════════════
SYSTEM_PROMPT = """ROLE

You are the Chief Editor of a professional Arabic cryptocurrency newsroom.

You are NOT a translator.

You are an editor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MISSION

The input is already preprocessed by Python.

Assume that:

- duplicated RSS lines were removed
- duplicated hashtags were removed
- signatures were removed
- obvious junk was removed

Your only task is to understand the facts and publish a professional Arabic news article.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EDITORIAL PRINCIPLES

Identify the SINGLE most important fact.

Build the headline around that fact.

Build the body around supporting facts.

Delete everything that does not strengthen the main story.

A news article is a hierarchy of facts.

The most important fact comes first.
Less important facts come later.
Irrelevant facts are removed.

Write like a Reuters financial editor.

Prioritize clarity over creativity.
Prioritize facts over wording.

Remove weak sentences.
Remove unnecessary context.
Every sentence must justify its existence.

Forget the original wording completely.
Imagine the source is your private notes.
Write a completely new article.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ABSOLUTE RULES

OFFICIAL ENTITY POLICY

Company names, exchange names, ETF names,
blockchain names, protocol names,
cryptocurrency names,
must remain in their official English spelling.

Never transliterate unknown names.
If confidence is low, preserve the original English name.

Bitcoin, Ethereum, Solana, BNB, XRP, Dogecoin,
Tether, Circle, Coinbase, BlackRock, MicroStrategy.

Never output: بتكوين، بيت كوين، بلاك روك، كوين بيس.
These names are immutable.

FINANCIAL TERMINOLOGY POLICY

Use established Arabic financial terminology.
Never translate financial idioms literally.

Inflows → تدفقات صافية
Outflows → تدفقات خارجة
Momentum → زخم
Holdings → حيازات
Spot ETF → صندوق تداول فوري
Assets under management → الأصول المدارة
Bullish → إيجابي
Bearish → سلبي

Never invent literal expressions.
If an idiom cannot be translated naturally,
rewrite the sentence from its meaning.

SOURCE ATTRIBUTION

Publisher names (Benzinga, CoinDesk, Cointelegraph, BeInCrypto, Decrypt)
are metadata.
Never include them in the article
unless the source itself is the subject of the news.

NO HANGING ATTRIBUTION

Never end an article with a vague attribution.

Forbidden:
- وفقاً لتقارير
- وفقاً لمصادر
- بحسب التقارير
- وفقاً لـ...
- وتشير التقارير إلى...

Either name the SPECIFIC source (وفقاً لتقرير البنك المركزي الأمريكي)
or remove the sentence entirely.
A sentence without a named source is noise.

Never:

- translate literally
- repeat the headline
- repeat information
- repeat hashtags
- repeat sentences
- copy the article structure
- copy machine translation
- invent facts
- speculate
- exaggerate
- use promotional language

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INPUT QUALITY GATE (MANDATORY)

Before extracting any facts, evaluate the source quality.

Reject if the source contains:

- broken words
- mixed Arabic and English inside the same word
- corrupted machine translation
- incomplete sentences
- malformed RSS titles
- unreadable grammar

If the source is corrupted:

1. Ignore the broken wording.
2. Recover only the facts that are clearly understandable.
3. Reconstruct the article from those recovered facts.
4. Never copy corrupted text.

If the facts cannot be recovered with high confidence:

Return:
{"status": "reject", "reason": "corrupted_source"}

Never guess missing information.

CORRUPTED TEXT POLICY

Words such as:

إطلاقes
Launchingات
Developer النظام
Protocol الخاصة

are evidence of corrupted translation.

Never copy corrupted words.
Never attempt to repair individual words.
Recover the meaning and rewrite from scratch.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEWSROOM FILTER

Before writing, classify every source sentence.

A = Verified fact. Keep.
B = Opinion. Delete unless attributed to a person or organization.
C = Market commentary. Delete.
D = Generic explanation. Delete.
E = Repeated information. Delete.

Only Category A should normally remain.
Never publish Category C or D.

BODY RULES

The body MUST expand the headline.

Every sentence must introduce NEW information.
Every sentence must contain at least one concrete fact.
If a sentence contains no measurable or verifiable information, delete it.
Never write sentences only to improve flow.

If two sentences express the same idea,
keep only the stronger one.

Use concise financial journalism.

Avoid AI filler.

Forbidden examples:

- وسط ترقب الأسواق
- مما يعزز الزخم
- في خطوة تعكس
- خلال الفترة الحالية
- التطبيق القاتل
- غير قواعد اللعبة

PARAGRAPH STYLING

Each body paragraph MUST start with one relevant emoji.

Choose based on content:
⚡ breaking / urgent fact
📈 data / statistics / market movement
🔥 major development / key event
💰 financial impact / numbers
🔧 technical / protocol detail
⚠️ risk / warning / regulation
🌐 regulation / geopolitics / institutional

Each paragraph: 1-2 sentences maximum.
Every sentence must contain a concrete fact.
If a sentence has no fact, delete it.

BODY METADATA CLEANUP

Never include RSS metadata in the body.
These are metadata, not article content:
- ظهر لأول مرة على
- نُشر في
- حسبما أفادت
- بحسب موقع
- كما نشرته
- منشور الأخبار
- First appeared on
- Originally published on
- Source:
- Read more
- via [publisher name]

Delete any sentence that is pure metadata.

FORMAT CONTAINMENT

Never output format labels in any field.
Forbidden in headline AND body:
- منشور الأخبار العاجلة:
- الأخبار العاجلة:
- عاجل:
- خبر عاجل:
- Breaking News:
- Urgent:

The importance field controls the emoji (🚨🔴🔵⚪).
The format field controls the layout.
Never reveal these labels in the article text.

TRANSLITERATION SAFETY

Never transliterate proper nouns into Arabic
using non-Arabic scripts (Telugu, Devanagari, etc.).

If a name cannot be written in Arabic correctly,
keep the English name unchanged.

Examples:
Wrong: غ్రేస్కేల (Telugu script)
Correct: Grayscale (keep English)

Wrong: بلاك روك (invented transliteration)
Correct: BlackRock (keep English)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HEADLINE RULES

Headline:

- short
- factual
- informative
- no clickbait
- maximum 15 words

HEADLINE CLEANUP

Never prefix the headline with:
- الأخبار العاجلة
- عاجل
- منشور الأخبار العاجلة
- خبر عاجل
- إلحاحي
- flash

The importance field controls the emoji (🚨🔴🔵⚪).
The headline itself must state the FACT only.
No labels, no prefixes, no metadata.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ARTICLE TYPES

Automatically choose ONE format.

STANDARD
headline
paragraph

-----------------------

BULLET SUMMARY
headline
1.
2.
3.
4.

-----------------------

ECONOMIC DATA
indicator
Previous
Forecast
Actual
One-line explanation

-----------------------

ETF FLOW ARTICLES

If the article reports ETF fund inflows or outflows:
Use "economic" format.
Output ONLY: fund name, direction, amount.

Direction keywords:
إيجابي (positive inflow)
سلبي (negative outflow)
تعادل (neutral / zero)

Do NOT:
- Write analysis or commentary
- Generate cryptocurrency hashtags
- Mention fund strategies or holdings
- Explain market implications

Example output:
{
  "headline": "IBIT — تدفقات إيجابية +100.5M",
  "body": "",
  "format": "economic",
  "hashtag": "",
  "importance": "medium"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ANALYSIS

If the source is an opinion,
prediction,
or technical analysis,

make this explicit.

Use:

- بحسب تحليل...
- وفقاً لتقرير...
- يرى محللون...

Never present opinions as facts.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HASHTAGS

Generate a hashtag ONLY IF:

1. The cryptocurrency is the main subject.
2. The cryptocurrency is explicitly mentioned in the source.
3. The news is directly about that cryptocurrency.

Otherwise return an empty hashtag.

Never generate hashtags from verbs, adjectives,
common English words, company names, locations,
or ticker-like words.

HASHTAG BLACKLIST

These are NEVER valid hashtags:
#ES #TO #IN #AT #BY #OR #AS #DO #GO #NO #SO
Common English words are not crypto tickers.

Never trust the source hashtag.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ENTITY VALIDATION

Before mentioning any cryptocurrency, token, ticker,
protocol, blockchain, ETF or company:

Validate that it is the PRIMARY subject of the news.
Never infer a cryptocurrency from a common English word.

Examples of FALSE positives:
"near support" "near approval" "nearly"
are NOT references to NEAR Protocol.

"op position" "op revenue" "operation"
are NOT references to Optimism.

Only identify a crypto entity if the source explicitly
refers to it by name, ticker, or $ symbol.

ENTITY CONFIDENCE RULE

Never guess entity names.
Only mention an entity if confidence is very high.
If confidence is low, omit the entity instead of hallucinating it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OUTPUT

Return ONLY JSON.

Normal article:
{
  "headline": "",
  "body": "",
  "format": "standard | bullets | economic",
  "hashtag": "",
  "importance": "low | medium | high | breaking"
}

Rejected article (corrupted source):
{
  "status": "reject",
  "reason": "corrupted_source"
}

Never return markdown.
Never return explanations.
Never return anything outside JSON."""


# ═══════════════════════════════════════════════════════════
# 🔧 JSON Output Parser (مشترك — يستخدمه كل المترجمين)
# ═══════════════════════════════════════════════════════════

# وسوم ليست عملات كريبتو — حظر كامل
_HASHTAG_BLACKLIST = {
    "es", "to", "in", "on", "at", "by", "or", "as", "is", "be", "do", "go",
    "no", "so", "up", "if", "am", "an", "my", "he", "we", "me", "us", "it",
    "ai", "tv", "io", "de", "la", "el", "un", "en", "lo", "su", "se",
}


def parse_json_output(text: str) -> Optional[Dict[str, str]]:
    """تحليل مخرجات JSON من أي مترجم.

    يدعم:
    - JSON نقي
    - JSON داخل ```json ... ```
    - JSON مضمن داخل نص آخر

    لا يدعم:
    - التنسيقات القديمة (العنوان: / الخبر:)
    - النص العادي بدون JSON
    """
    if not text:
        return None

    cleaned = text.strip()

    # إزالة ```json ... ``` wrapper
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\n?', '', cleaned)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()

    # محاولة 1: JSON مباشر
    try:
        data = json.loads(cleaned)
        return _validate_result(data)
    except (json.JSONDecodeError, AttributeError, KeyError):
        pass

    # محاولة 2: استخراج JSON من نص مختلط — أوجد أول { وآخر }
    start = cleaned.find('{')
    if start >= 0:
        depth = 0
        end = -1
        for i in range(start, len(cleaned)):
            if cleaned[i] == '{':
                depth += 1
            elif cleaned[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > start:
            try:
                data = json.loads(cleaned[start:end + 1])
                return _validate_result(data)
            except (json.JSONDecodeError, AttributeError, KeyError):
                pass

    return None


def _validate_result(data: Dict) -> Optional[Dict[str, str]]:
    """فحص صحة نتيجة JSON — يدعم reject أيضاً
    يتضمن: إزالة بادئات التصنيف، فلتر الهاشتاغات، توحيد المرادفات
    """
    if not isinstance(data, dict):
        return None

    # حالة رفض: مصدر معطوب
    if data.get("status") == "reject":
        return {"_rejected": True, "reason": data.get("reason", "unknown")}

    headline = (data.get("headline") or "").strip()
    if not headline or len(headline) < 3:
        return None

    # ═══ إزالة بادئات التصنيف من العنوان ═══
    _LABEL_PREFIXES = [
        re.compile(r'^منشور\s+الأخبار\s+العاجلة\s*:\s*', re.IGNORECASE),
        re.compile(r'^الأخبار\s+العاجلة\s*:\s*', re.IGNORECASE),
        re.compile(r'^عاجل\s*:\s*', re.IGNORECASE),
        re.compile(r'^خبر\s+عاجل\s*:\s*', re.IGNORECASE),
        re.compile(r'^Breaking\s+News\s*:\s*', re.IGNORECASE),
    ]
    for pat in _LABEL_PREFIXES:
        headline = pat.sub('', headline).strip()
    if not headline or len(headline) < 3:
        return None

    body = (data.get("body") or "").strip()

    # ═══ إزالة بادئات التصنيف من كل سطر في body ═══
    if body:
        body_lines = body.split("\n")
        cleaned_body = []
        for bline in body_lines:
            bline_s = bline.strip()
            for pat in _LABEL_PREFIXES:
                bline_s = pat.sub('', bline_s).strip()
            if bline_s:
                cleaned_body.append(bline_s)
        body = "\n".join(cleaned_body).strip()

    fmt = (data.get("format") or "standard").strip()
    if fmt not in ("standard", "bullets", "economic"):
        fmt = "standard"

    hashtag = (data.get("hashtag") or "").strip().lstrip("#")
    if hashtag:
        # فلتر: حظر الوسوم القصيرة أو كلمات إنجليزية شائعة
        if hashtag.lower() in _HASHTAG_BLACKLIST or len(hashtag) <= 2:
            hashtag = ""
        else:
            # توحيد المرادفات: BITCOIN → BTC, ETHEREUM → ETH
            canonical = COIN_NAME_TO_TICKER.get(hashtag.lower(), hashtag.upper())
            hashtag = "#" + canonical

    importance = (data.get("importance") or "medium").strip()
    if importance not in ("low", "medium", "high", "breaking"):
        importance = "medium"

    return {
        "headline": headline,
        "body": body,
        "format": fmt,
        "hashtag": hashtag,
        "importance": importance,
    }


def _parse_raw_as_fallback(text: str) -> Optional[Dict[str, str]]:
    """تحويل نص عادي (من Google Translate) إلى dict"""
    if not text or len(text) < 5:
        return None

    parts = text.split("\n", 1)
    headline = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else ""

    if not headline or len(headline) < 3:
        return None

    return {
        "headline": headline,
        "body": body,
        "format": "standard",
        "hashtag": "",
        "importance": "medium",
    }


# ═══════════════════════════════════════════════════════════
# 🤖 Gemini Translation (Async — مكالمة واحدة)
# ═══════════════════════════════════════════════════════════
class GeminiTranslator:
    """مترجم Gemini — مكالمة واحدة مع System Prompt محسّن"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._models: List[str] = []
        self._initialized = False
        self._lock = asyncio.Lock()

    async def _init(self):
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)

                candidates = [
                    "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest",
                    "gemini-2.5-pro", "gemini-2.0-pro", "gemini-1.5-pro-latest",
                ]

                for model_name in candidates:
                    try:
                        model = genai.GenerativeModel(model_name, system_instruction=SYSTEM_PROMPT)
                        test = await asyncio.to_thread(
                            model.generate_content,
                            "test",
                            generation_config={"max_output_tokens": 5}
                        )
                        if test and test.text:
                            self._models.append(model_name)
                            log.info(f"✅ Gemini model ready: {model_name}")
                    except Exception:
                        continue

                if not self._models:
                    try:
                        models_list = list(genai.list_models())
                        for m in models_list:
                            name = m if isinstance(m, str) else getattr(m, 'name', str(m))
                            if name and ("flash" in name.lower() or "pro" in name.lower()):
                                try:
                                    model = genai.GenerativeModel(name, system_instruction=SYSTEM_PROMPT)
                                    test = await asyncio.to_thread(
                                        model.generate_content,
                                        "test",
                                        generation_config={"max_output_tokens": 5}
                                    )
                                    if test and test.text:
                                        self._models.append(name)
                                        log.info(f"✅ Gemini auto-discovered: {name}")
                                except Exception:
                                    continue
                    except Exception as e:
                        log.warning(f"Gemini auto-discovery failed: {e}")

                self._initialized = True
            except Exception as e:
                log.warning(f"Gemini init failed: {e}")
                self._initialized = True

    async def translate(self, text: str, missing_names: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
        """مكالمة واحدة: clean → Gemini → parse JSON"""
        await self._init()
        if not self._models:
            return None

        import google.generativeai as genai

        for model_name in self._models:
            try:
                # تنظيف النص قبل الإرسال
                cleaned_text = clean_news(text)
                if not cleaned_text or len(cleaned_text) < 15:
                    cleaned_text = text

                # إضافة تنبيه أسماء مفقودة إن وُجدت
                user_content = cleaned_text
                if missing_names:
                    user_content += (
                        f"\n\nREMINDER: The following names MUST appear"
                        f" in the output: {', '.join(missing_names)}"
                    )

                model = genai.GenerativeModel(model_name, system_instruction=SYSTEM_PROMPT)
                response = await asyncio.to_thread(
                    model.generate_content,
                    user_content,
                    generation_config={
                        "temperature": 0.3,
                        "top_p": 0.8,
                        "top_k": 40,
                        "max_output_tokens": 800,
                    }
                )

                if response and response.text:
                    result = parse_json_output(response.text.strip())
                    if result:
                        log.info(f"✅ Gemini ({model_name}): translation success"
                                 f" [{result['format']}/{result['importance']}]")
                        return result

            except Exception as e:
                log.info(f"⏭️ Gemini ({model_name}) failed: {str(e)[:60]}")
                continue

        return None


# ═══════════════════════════════════════════════════════════
# 🔄 Fallback Translators
# ═══════════════════════════════════════════════════════════
class GroqTranslator:
    """Fallback: Groq API"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def translate(self, text: str) -> Optional[Dict[str, str]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 800,
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result_text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        if result_text and len(result_text) > 5:
                            result = parse_json_output(result_text)
                            if result:
                                log.info("✅ Groq translation success")
                                return result
                            # fallback: treat as raw text
                            log.info("✅ Groq: using raw text fallback")
                            return _parse_raw_as_fallback(result_text)
        except Exception as e:
            log.warning(f"Groq translation failed: {e}")
        return None


class OpenRouterTranslator:
    """Fallback: OpenRouter"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def translate(self, text: str) -> Optional[Dict[str, str]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={
                        "model": "qwen/qwen-2.5-72b-instruct",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 800,
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/news-bot",
                        "X-Title": "News Bot",
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result_text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        if result_text and len(result_text) > 5:
                            result = parse_json_output(result_text)
                            if result:
                                log.info("✅ OpenRouter translation success")
                                return result
                            log.info("✅ OpenRouter: using raw text fallback")
                            return _parse_raw_as_fallback(result_text)
        except Exception as e:
            log.warning(f"OpenRouter translation failed: {e}")
        return None


class GoogleTranslator:
    """Fallback المجاني: Google Translate — يُرجع نصاً عادياً"""

    async def translate(self, text: str) -> Optional[str]:
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
                    log.info("✅ Google Translate success")
                    return result
        except Exception as e:
            log.warning(f"Google Translate failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# 🏭 Translation Manager
# ═══════════════════════════════════════════════════════════
class TranslationManager:
    """مدير الترجمة الموحد — يُرجع Dict أو None"""

    def __init__(self, config: BotConfig):
        self.config = config
        self.gemini = GeminiTranslator(config.GEMINI_API_KEY) if config.GEMINI_API_KEY else None
        self.groq = GroqTranslator(config.GROQ_API_KEY) if config.GROQ_API_KEY else None
        self.openrouter = OpenRouterTranslator(config.OPENROUTER_API_KEY) if config.OPENROUTER_API_KEY else None
        self.google = GoogleTranslator()

    # كلمات إنجليزية شائعة تُسبب false positives — تحتاج uppercase أو $ أو سياق واضح
    _AMBIGUOUS = {"near", "op", "sol", "dot", "link", "apt", "sei", "ton",
                  "mat", "avax", "arb", "run", "sui", "sea", "top", "fit",
                  "meta", "atom", "one", "all", "sun", "moon", "star", "es"}

    def _extract_entities(self, text: str) -> List[str]:
        """استخراج الكيانات — كلمات مبهمة تحتاج uppercase أو رمز"""
        found = []
        for name in sorted(CRITICAL_NAMES, key=len, reverse=True):
            if name in self._AMBIGUOUS:
                # فقط كلمة مستقلة uppercase (NEAR) أو مع رمز ($NEAR, #NEAR)
                if (re.search(rf'\b{name.upper()}\b', text)
                    or f'${name.upper()}' in text
                    or f'#{name.upper()}' in text):
                    found.append(name)
            else:
                if name in text.lower():
                    found.append(name)
        return found

    def _verify_entities(self, original: str, translated: str) -> Tuple[bool, List[str]]:
        """التحقق من وجود الكيانات"""
        if not translated:
            return False, ["(empty)"]
        entities = self._extract_entities(original)
        if not entities:
            return True, []
        translated_lower = translated.lower()
        missing = [n for n in entities if n not in translated_lower]
        return len(missing) == 0, missing

    # أسماء إنجليزية مسموحة في النص العربي
    _ALLOWED_ENGLISH = frozenset({
        "Bitcoin", "Ethereum", "Solana", "Binance", "Coinbase", "USDT", "USDC",
        "Solana", "Cardano", "Ripple", "BlackRock", "MicroStrategy", "Grayscale",
        "Fidelity", "SEC", "ETF", "DeFi", "NFT", "Web3", "Near", "Op",
        "BitMEX", "CoinDesk", "Cointelegraph", "BeInCrypto", "Decrypt", "Blockworks",
        "Vitalik", "Satoshi", "Saylor", "Gensler", "Dorsey", "Buterin", "CZ",
        "Litecoin", "Dogecoin", "Avalanche", "Polkadot", "Chainlink", "Polygon",
        "Tron", "Uniswap", "Aptos", "Arbitrum", "Optimism", "Stellar", "Hedera",
        "Cosmos", "Fantom", "Aave", "Tether", "Circle", "OKX", "Kraken", "Bybit",
        "Ripple", "Shiba", "Pepe", "Toncoin", "Hedera", "Near", "Sui", "Sei",
        "IBIT", "FBTC", "ARKK", "GBTC", "ETHA", "HODL", "ETH",
        "BTC", "XRP", "BNB", "ADA", "DOGE", "AVAX", "DOT", "LINK", "POL",
        "LTC", "TRX", "UNI", "APT", "ARB", "SUI", "SEI", "TON", "FTM",
        "ATOM", "XLM", "HBAR", "SHIB", "PEPE", "DAI",
    })

    # سكريبتات يونيكود ممنوعة (ليست عربية ولا لاتينية)
    _WRONG_SCRIPTS = re.compile(
        r'[\u0C00-\u0C7F\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F'
        r'\u0B00-\u0B7F\u0E00-\u0E7F\u1000-\u109F\u0D00-\u0D7F'
        r'\u0A80-\u0AFF\u0B80-\u0BFF\u0C80-\u0CFF\u0D80-\u0DFF]'
    )

    def _is_quality_good(self, text: str) -> bool:
        """التحقق من جودة النص العربي — فحص شامل

        يكشف:
        1. نسبة العربية المنخفضة
        2. سكريبتات يونيكود خاطئة (Telugu, Devanagari...)
        3. كلمات إنجليزية مشبوهة
        4. بادئات عناوين ممنوعة
        5. تسرب أسماء المصادر
        """
        if not text or len(text) < 5:
            return False

        # (1) فحص السكريبتات الخاطئة — Telugu, Devanagari, إلخ
        wrong_chars = self._WRONG_SCRIPTS.findall(text)
        if wrong_chars:
            log.warning(f"Wrong Unicode script detected: {len(wrong_chars)} chars")
            return False

        # (2) نسبة العربية
        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        if len(text) > 20 and arabic_chars / len(text) < 0.25:
            log.warning(f"Low Arabic ratio: {arabic_chars/len(text)*100:.0f}%")
            return False

        # (3) كلمات إنجليزية مشبوهة (ليست في القائمة المسموحة)
        english_words = re.findall(r'[a-zA-Z]{3,}', text)
        suspicious = [w for w in english_words if w not in self._ALLOWED_ENGLISH]
        if suspicious:
            log.warning(f"Blocked: suspicious English words: {suspicious[:5]}")
            return False

        # (4) بادئات عناوين ممنوعة
        bad_prefixes = [
            r'^الأخبار\s+العاجلة\s*:',
            r'^عاجل\s*:',
            r'^منشور\s+الأخبار\s+العاجلة\s*:',
            r'^خبر\s+عاجل\s*:',
        ]
        for pat in bad_prefixes:
            if re.search(pat, text):
                log.warning(f"Blocked: forbidden headline prefix")
                return False

        return True

    def _is_body_quality_good(self, body: str) -> bool:
        """فحص جودة النص (body) — نفس معايير _is_quality_good"""
        if not body or len(body) < 5:
            return True  # body فارغ مسموح

        # فحص السكريبتات الخاطئة
        if self._WRONG_SCRIPTS.findall(body):
            log.warning(f"Wrong Unicode script in body")
            return False

        # كلمات إنجليزية مشبوهة في body
        english_words = re.findall(r'[a-zA-Z]{3,}', body)
        suspicious = [w for w in english_words if w not in self._ALLOWED_ENGLISH]
        if suspicious:
            log.warning(f"Blocked: suspicious English in body: {suspicious[:5]}")
            return False

        return True

    def _truncate(self, text: str, max_len: int = 1200) -> str:
        """قص النص عند نهاية جملة"""
        if len(text) <= max_len:
            return text
        chunk = text[:max_len]
        for punct in ('. ', '.\n', '! ', '? '):
            last = chunk.rfind(punct)
            if last > max_len * 0.5:
                return chunk[:last + 1]
        last_space = chunk.rfind(' ')
        if last_space > max_len * 0.5:
            return chunk[:last_space]
        return chunk

    async def translate(self, text: str, force: bool = False, source_name: str = "") -> Optional[Dict[str, str]]:
        """ترجمة النص — يُرجع dict {headline, body, format, hashtag, importance} أو None

        LLM translators (Gemini, Groq, OpenRouter): نص إنجليزي خام — البرومبت يعالج الأسماء.
        Google Translate: حماية الكيانات داخلياً.

        source_name: اسم المصدر لإبلاغ source_quality.
        """
        if not text or len(text) < 3:
            return None

        text = self._truncate(text)
        cache_key = translation_cache._hash_key(text)

        if not force:
            cached = await translation_cache.get(cache_key)
            if cached:
                log.info("💾 Translation cache hit")
                return cached

        # ═══ الطبقة 1: Gemini (نص خام — البرومبت يتعامل مع الأسماء) ═══
        if self.gemini:
            result = await self.gemini.translate(text)
            if result:
                # Gemini رفض الخبر (مصدر معطوب) → تخطي كل الفولباكات
                if result.get("_rejected"):
                    log.warning(f"   🚫 Gemini rejected article: {result.get('reason', 'unknown')}")
                    if source_name:
                        source_quality.record_rejection(source_name, "Gemini rejected: corrupted_source")
                    return None
                if self._is_quality_good(result["headline"]) and self._is_body_quality_good(result.get("body", "")):
                    check_text = result["headline"] + " " + result.get("body", "")
                    ok, missing = self._verify_entities(text, check_text)

                    if not ok:
                        log.warning(f"   🔄 Gemini retry — missing: {missing}")
                        retry = await self.gemini.translate(text, missing_names=missing)
                        if retry:
                            if retry.get("_rejected"):
                                log.warning(f"   🚫 Gemini retry rejected: {retry.get('reason', 'unknown')}")
                                if source_name:
                                    source_quality.record_rejection(source_name, "Gemini retry rejected: corrupted_source")
                                return None
                            if self._is_quality_good(retry["headline"]) and self._is_body_quality_good(retry.get("body", "")):
                                await translation_cache.set(cache_key, retry)
                                return retry
                        # فشل Retry → جرب الفولباكات
                    else:
                        await translation_cache.set(cache_key, result)
                        return result

        # ═══ الطبقة 2: Groq (نص خام) ═══
        if self.groq:
            result = await self.groq.translate(text)
            if result and self._is_quality_good(result["headline"]) and self._is_body_quality_good(result.get("body", "")):
                await translation_cache.set(cache_key, result)
                return result

        # ═══ الطبقة 3: OpenRouter (نص خام) ═══
        if self.openrouter:
            result = await self.openrouter.translate(text)
            if result and self._is_quality_good(result["headline"]) and self._is_body_quality_good(result.get("body", "")):
                await translation_cache.set(cache_key, result)
                return result

        # ═══ الطبقة 4: Google Translate (حماية الكيانات داخلياً) ═══
        raw = await self.google.translate(text)
        if raw:
            arabic_chars = sum(1 for c in raw if '\u0600' <= c <= '\u06FF')
            if len(raw) > 20 and arabic_chars / len(raw) >= 0.15:
                fallback = _parse_raw_as_fallback(raw)
                if fallback:
                    await translation_cache.set(cache_key, fallback)
                    return fallback

        log.warning("   ❌ All translation methods failed")
        if source_name:
            source_quality.record_rejection(source_name, "All translation methods failed")
        return None

    async def translate_item(self, item) -> None:
        """ترجمة خبر كامل — يملأ حقول item مباشرة"""
        title = getattr(item, 'title', '') or ''
        summary = getattr(item, 'summary', '') or ''
        source_name = getattr(item, 'source', '') or ''

        # دمج العنوان والملخص
        combined = (title + "\n" + summary).strip() if summary else title.strip()
        if not combined:
            return

        result = await self.translate(combined, source_name=source_name)
        if not result:
            return

        # ملء حقول item مباشرة
        item.title_ar = result["headline"]
        item.summary_ar = result.get("body", "")
        item.news_format = result.get("format", "standard")
        item.importance = result.get("importance", "medium")

        # تحديث العملات من الهاشتاغ — مع dedup عبر COIN_NAME_TO_TICKER
        hashtag = result.get("hashtag", "")
        if hashtag:
            tag = hashtag.lstrip("#").upper()
            # خريطة: BITCOIN → BTC, ETHEREUM → ETH, إلخ
            mapped_tag = COIN_NAME_TO_TICKER.get(tag.lower(), tag)
            # فحص: هل العملة موجودة فعلاً (حتى لو باسم مختلف)؟
            existing_mapped = {COIN_NAME_TO_TICKER.get(c.lower(), c.upper()) for c in (item.coins or [])}
            if mapped_tag not in existing_mapped:
                if item.coins:
                    item.coins = item.coins + [mapped_tag]
                else:
                    item.coins = [mapped_tag]
