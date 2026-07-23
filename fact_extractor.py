"""
🐋 Whale News Bot v3 - مستخرج الحقائق
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
استخراج حقائق منظّمة من الأخبار باستخدام regex وأنماط مطابقة — بدون أي مكالمة AI.
نظام حتمي قابل للتصحيح: النص يدخل → الحقائق تخرج.

المبدأ: كل شيء محدد سلفاً — لا تخمين، لا ذكاء اصطناعي.
════════════════════════════════════════════════════════════════
"""

import re
from typing import List, Tuple, Optional, Dict, Set

from models import Fact, ExtractedFacts
from config import COIN_MAP, COMPANIES, PEOPLE, log


# ═══════════════════════════════════════════════════════════════
# 🔢 ثوابت تحويل الأرقام المختصرة
# ═══════════════════════════════════════════════════════════════
_SUFFIX_MULTIPLIER: Dict[str, float] = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "t": 1_000_000_000_000,
}

_WORD_MULTIPLIER: Dict[str, float] = {
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000,
}


# ═══════════════════════════════════════════════════════════════
# 🎯 أنماط regex للكميات المالية
# ═══════════════════════════════════════════════════════════════
# --- مبالغ بالدولار مع اختصارات: $48M, $1.2B, $350K, $500 ---
_RE_DOLLAR_SHORT = re.compile(
    r"""
    \$
    (?:
        (?P<short>\d{1,3}(?:\.\d+)?)
        \s*
        (?P<suffix>[KkMmBbTt])
        |
        (?P<plain>[\d,]+(?:\.\d+)?)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# --- مبالغ بالدولار + كلمات: $48 million, $1.2 billion ---
_RE_DOLLAR_WORDS = re.compile(
    r"""
    \$
    \s*
    (?P<num>\d{1,3}(?:\.\d+)?)
    \s+
    (?P<word>million|billion|trillion|thousand)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# --- كميات عملات: 400 BTC, 15,000 ETH, 0.5 BTC ---
_RE_COIN_AMOUNT = re.compile(
    r"""
    (?P<amount>[\d,]+(?:\.\d+)?)
    \s+
    (?P<coin>BTC|ETH|SOL|XRP|ADA|DOGE|AVAX|DOT|LINK|POL|MATIC|
           LTC|TRX|UNI|AAVE|NEAR|APT|ARB|OP|SUI|SEI|PEPE|SHIB|
           TON|FTM|ATOM|XLM|HBAR|BNB|USDT|USDC|DAI|BCH|CBBTC|IBIT|FBTC)
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# --- مبالغ بالكلمات بدون علامة دولار: 48 million tokens ---
_RE_WORD_AMOUNT = re.compile(
    r"""
    \b
    (?P<num>\d{1,3}(?:\.\d+)?)
    \s+
    (?P<word>million|billion|trillion|thousand)
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ═══════════════════════════════════════════════════════════════
# 🔨 أنماط regex للأفعال — مرتبة حسب الأولوية
# ═══════════════════════════════════════════════════════════════
# الأفعال المحددة (أولوية عالية) تُفحص أولاً — تمنع مطابقة أفعال عامة
_ACTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # --- اختراق / سرقة / تصريف (أولوية قصوى — أحداث سلبية حاسمة) ---
    (
        re.compile(
            r"\b(hacked|exploit(?:ed|s)?|breached|drained|stolen|compromised|"
            r"rekt|rug\s+pull|flash\s+loan\s+(?:attack|exploit)|"
            r"siphoned|drains?|looted|embezzled)\b",
            re.IGNORECASE,
        ),
        "hacked",
    ),
    # --- شراء / استثمار / تجميع ---
    (
        re.compile(
            r"\b(bought|purchased|acquired|invested|invests?|investing|"
            r"buys?|purchases?|acquires?|accumulat(?:e|ed|es|ing)|"
            r"scoop(?:ed|s)?\s+up|loaded\s+up|grabbed|picked\s+up)\b",
            re.IGNORECASE,
        ),
        "bought",
    ),
    # --- بيع / تصفية ---
    (
        re.compile(
            r"\b(sold|sells?|selling|offloaded|offloads?|dumped|dump(?:s|ing)?|"
            r"divested|divest(?:s|ed|ing)|unloaded)\b",
            re.IGNORECASE,
        ),
        "sold",
    ),
    # --- حظر / تقييد ---
    (
        re.compile(
            r"\b(banned|bans?|banning|restricted|restrict(?:s|ing|ed)?|"
            r"crackdown|sanctioned|sanctions?|blacklisted|froze(?:n)?)\b",
            re.IGNORECASE,
        ),
        "banned",
    ),
    # --- موافقة ---
    (
        re.compile(
            r"\b(approved|approves?|approving|greenl(?:it|ighted)|"
            r"cleared|authorized|authorised|gave\s+(?:the\s+)?go-ahead)\b",
            re.IGNORECASE,
        ),
        "approved",
    ),
    # --- رفض ---
    (
        re.compile(
            r"\b(rejected|rejects?|rejecting|denied|denies?|denying|"
            r"blocked|turn(?:ed|s)?\s+down|dismissed|refused|veto(?:ed|oes)?)\b",
            re.IGNORECASE,
        ),
        "rejected",
    ),
    # --- شراكة ---
    (
        re.compile(
            r"\b(partnered|partners?|partnering|collaborated|collaborates?|"
            r"collaborating|teamed\s+up|joins?\s+forces|strategic\s+partnership|"
            r"integrates?|integrating)\b",
            re.IGNORECASE,
        ),
        "partnered",
    ),
    # --- إدراج ---
    (
        re.compile(
            r"\b(listed|lists?|listing|delisted|delists?|delisting|"
            r"trading\s+goes\s+live|added\s+to\s+(?:exchange|trading))\b",
            re.IGNORECASE,
        ),
        "listed",
    ),
    # --- تقسيم / حرق ---
    (
        re.compile(
            r"\b(halv(?:ed|ing)|airdrop(?:ped|s)?|fork(?:ed|s)?|"
            r"burn(?:ed|t|s)?|burning|token\s+burn|destroyed)\b",
            re.IGNORECASE,
        ),
        "burned",
    ),
    # --- إطلاق / إعلان (أولوية منخفضة — كلمة عامة) ---
    (
        re.compile(
            r"\b(launched|launch(?:es|ing)?|announced|announces?|announcing|"
            r"unveiled|unveils?|introduced|introduces?|introducing|"
            r"rolled\s+out|debuted|released|releases?|releasing|"
            r"dropped|drops?|went\s+live|goes\s+live|is\s+live)\b",
            re.IGNORECASE,
        ),
        "launched",
    ),
]

# --- مجموعة أفعال الإعلان/الإطلاق: إذا وُجد فعل أقوى، نتجاهلها ---
_ANNOUNCE_ACTIONS = {"launched"}


# ═══════════════════════════════════════════════════════════════
# 😊 كلمات المشاعر
# ═══════════════════════════════════════════════════════════════
_POSITIVE_WORDS: Set[str] = {
    # ارتفاع
    "surge", "surged", "surging", "surges",
    "rally", "rallied", "rallying", "rallies",
    "soared", "skyrocket", "skyrocketed", "skyrockets",
    "boom", "breakthrough",
    # أرباح ومكاسب
    "gain", "gained", "gains", "gaining",
    "profit", "profits", "profitable",
    "ath", "all-time high", "all-time highs", "record high",
    "record", "breaks record", "breaks records",
    # شراء واستثمار (إيجابي للمستثمر)
    "bought", "buys", "buying", "purchased", "purchases",
    "acquired", "acquires", "invested", "invests", "investing",
    "accumulated", "accumulating", "accumulation",
    # موافقة
    "approved", "approval", "approves", "approving",
    "greenlit", "greenlighted", "cleared", "authorized",
    # إطلاق
    "launched", "launches", "launching",
    "listed", "listing", "partnership", "partnered",
    "collaboration", "collaborated",
    # سوق إيجابي
    "bullish", "bull run", "bull market", "moon",
    "recovery", "recovered", "recovering",
    "adoption", "adopted", "mainstream",
    "institutional", "institution",
    "boost", "boosted", "boosting", "boosts",
    "milestone", "success", "successful",
    "upgrade", "upgraded", "improvement", "innovative",
    "wins", "win", "winning",
    # مفاهيم إيجابية عامة
    "positive", "optimistic", "confidence", "confident",
    "surpassed", "surpasses", "reached", "reaches",
    "new high", "all-time", "first time", "historic",
    "stable", "strength", "strong", "stronger",
    "secure", "secured", "resilient",
}

_NEGATIVE_WORDS: Set[str] = {
    # انهيار
    "crash", "crashed", "crashing", "crashes",
    "plunge", "plunged", "plunging", "plunges",
    "dump", "dumped", "dumping", "dumps",
    "drop", "dropped", "dropping", "drops",
    "fall", "fell", "fallen", "falling", "falls",
    "decline", "declined", "declining", "declines",
    "slump", "slumped", "slumping",
    "tumble", "tumbled", "tumbling",
    "flash crash", "capitulation", "panic", "panic sell",
    # اختراق
    "hack", "hacked", "hacking", "hacks",
    "exploit", "exploited", "exploiting", "exploits",
    "breach", "breached", "breaching",
    "stolen", "theft", "vulnerability", "vulnerable",
    "drain", "drained", "draining", "drains",
    "siphoned", "looted", "compromised",
    # حظر ورفض
    "ban", "banned", "banning", "bans",
    "reject", "rejected", "rejecting", "rejects",
    "denied", "denying", "blocked", "refused",
    # خسائر
    "loss", "losses", "losing", "lost",
    "liquidated", "liquidation", "rekt",
    # احتيال
    "scam", "scammed", "scammer", "scammers",
    "rug pull", "rug pulled", "fraud", "fraudulent",
    # سوق سلبي
    "bearish", "bear market",
    "depeg", "depegged",
    "fud", "fear", "uncertainty", "doubt",
    "sanction", "sanctioned", "sanctions",
    "lawsuit", "sued", "suing", "sue",
    "seized", "freeze", "frozen", "forfeited",
    "bankrupt", "bankruptcy",
    "delisted", "delisting",
    "sold", "sells", "selling", "offloaded",
}


# ═══════════════════════════════════════════════════════════════
# 🛠️ دوال مساعدة
# ═══════════════════════════════════════════════════════════════

def _parse_number(raw: str) -> float:
    """
    تحويل سلسلة رقمية إلى عدد — يزيل الفواصل ويعالج الأرقام.
    مثال: "15,000" → 15000.0 | "1.2" → 1.2 | "350" → 350.0
    """
    raw = raw.strip().replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _expand_amount(num: float, suffix: str) -> float:
    """توسيع الرقم حسب اللاحقة: 48 + "M" → 48,000,000"""
    multiplier = _SUFFIX_MULTIPLIER.get(suffix.lower(), 1.0)
    return num * multiplier


def _expand_word_amount(num: float, word: str) -> float:
    """توسيع الرقم حسب الكلمة: 48 + "million" → 48,000,000"""
    multiplier = _WORD_MULTIPLIER.get(word.lower(), 1.0)
    return num * multiplier


def _dedup_amounts(amounts: List[Tuple], key_fn=None) -> List[Tuple]:
    """
    إزالة التكرار من قائمة المبالغ.
    نحتفظ بالأول فقط لأن النص قد يُكرر في العنوان.
    """
    seen: Set = set()
    result: List[Tuple] = []
    for item in amounts:
        key = key_fn(item) if key_fn else item
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# ═══════════════════════════════════════════════════════════════
# 🔍 دوال الاستخراج الرئيسية
# ═══════════════════════════════════════════════════════════════

def _scan_for_coins(text: str) -> List[str]:
    """
    البحث في النص عن أسماء العملات من COIN_MAP.
    ترتيب: الأطول أولاً (لتجنب مطابقة جزئية).
    يعيد: قائمة tickers بدون تكرار.
    """
    text_lower = text.lower()
    found: Set[str] = set()

    # الأطول أولاً — "bitcoin cash" قبل "bitcoin"
    sorted_keys = sorted(COIN_MAP.keys(), key=len, reverse=True)
    for key in sorted_keys:
        pattern = r"(?<![a-zA-Z])" + re.escape(key) + r"(?![a-zA-Z])"
        if re.search(pattern, text_lower):
            found.add(COIN_MAP[key])

    return sorted(found)


def _scan_for_companies(text: str) -> List[str]:
    """
    البحث في النص عن الشركات من COMPANIES.
    الأطول أولاً: "federal reserve" قبل "fed".
    """
    text_lower = text.lower()
    found: Set[str] = set()

    sorted_keys = sorted(COMPANIES.keys(), key=len, reverse=True)
    for key in sorted_keys:
        pattern = r"(?<![a-zA-Z])" + re.escape(key) + r"(?![a-zA-Z])"
        if re.search(pattern, text_lower):
            found.add(COMPANIES[key])

    return sorted(found)


def _scan_for_people(text: str) -> List[str]:
    """
    البحث في النص عن الأشخاص من PEOPLE.
    الأطول أولاً: "michael saylor" قبل "saylor".
    """
    text_lower = text.lower()
    found: Set[str] = set()

    sorted_keys = sorted(PEOPLE.keys(), key=len, reverse=True)
    for key in sorted_keys:
        pattern = r"(?<![a-zA-Z])" + re.escape(key) + r"(?![a-zA-Z])"
        if re.search(pattern, text_lower):
            found.add(PEOPLE[key])

    return sorted(found)


def _scan_for_actions(text: str) -> List[str]:
    """
    البحث في النص عن أفعال/أحداث معروفة.
    يعيد: قائمة الأفعال بدون تكرار (ترتيب الأولوية محفوظ).

    قاعدة هامة: إذا وُجد فعل محدد (مثل "bought")، نتجاهل الأفعال
    العامة (مثل "launched"/"announced") لأن "announced the purchase"
    لا يعني فعل "إطلاق" — بل إعلان عن شراء.
    """
    found: List[str] = []
    seen: Set[str] = set()

    for pattern, action_label in _ACTION_PATTERNS:
        if pattern.search(text):
            if action_label not in seen:
                # إذا وُجد فعل محدد وأردنا إضافة فعل إعلان عام
                if action_label in _ANNOUNCE_ACTIONS:
                    # نضيفه فقط إذا لم نجد فعلاً أقوى
                    if not any(a not in _ANNOUNCE_ACTIONS for a in found):
                        found.append(action_label)
                        seen.add(action_label)
                else:
                    found.append(action_label)
                    seen.add(action_label)

    return found


def _extract_dollar_amounts(text: str) -> List[Tuple[float, str]]:
    """
    استخراج كل مبالغ الدولار ($48M, $1.2B, $500, $48 million).
    يعيد: قائمة (القيمة_العددية, النص_للعرض) بدون تكرار.
    """
    results: List[Tuple[float, str]] = []

    # اختصارات: $48M, $1.2B, $350K
    for m in _RE_DOLLAR_SHORT.finditer(text):
        if m.group("short") and m.group("suffix"):
            num = float(m.group("short"))
            value = _expand_amount(num, m.group("suffix"))
            display = f"${m.group('short')}{m.group('suffix').upper()}"
            results.append((value, display))
        elif m.group("plain"):
            value = _parse_number(m.group("plain"))
            if value > 0:
                display = f"${m.group('plain')}"
                results.append((value, display))

    # كلمات: $48 million, $1.2 billion
    for m in _RE_DOLLAR_WORDS.finditer(text):
        num = float(m.group("num"))
        word = m.group("word")
        value = _expand_word_amount(num, word)
        display = f"${num} {word}"
        results.append((value, display))

    # إزالة التكرار — نفس القيمة العددية يُدمج
    return _dedup_amounts(results, key_fn=lambda x: x[0])


def _extract_coin_amounts(text: str) -> List[Tuple[float, str, str]]:
    """
    استخراج كميات العملات: "400 BTC", "15,000 ETH".
    يعيد: قائمة (العدد, رمز_العملة, النص_للعرض) بدون تكرار.
    """
    results: List[Tuple[float, str, str]] = []

    for m in _RE_COIN_AMOUNT.finditer(text):
        amount = _parse_number(m.group("amount"))
        coin = m.group("coin").upper()
        display = f"{m.group('amount')} {coin}"
        results.append((amount, coin, display))

    return _dedup_amounts(results, key_fn=lambda x: (x[0], x[1]))


def _extract_word_amounts(text: str) -> List[Tuple[float, str]]:
    """
    استخراج مبالغ بالكلمات بدون علامة دولار: "48 million".
    يعيد: قائمة (القيمة, النص_للعرض).
    """
    results: List[Tuple[float, str]] = []

    for m in _RE_WORD_AMOUNT.finditer(text):
        num = float(m.group("num"))
        word = m.group("word")
        value = _expand_word_amount(num, word)
        display = f"{num} {word}"
        results.append((value, display))

    return _dedup_amounts(results, key_fn=lambda x: x[0])


def _compute_sentiment(text: str) -> str:
    """
    تحليل المشاعر بالكلمات المفتاحية.
    القاعدة: الأكثر عدداً يفوز.
    يعيد: "positive" | "negative" | "neutral"
    """
    text_lower = text.lower()
    positive_count = 0
    negative_count = 0

    for word in _POSITIVE_WORDS:
        if re.search(r"(?<![a-zA-Z])" + re.escape(word) + r"(?![a-zA-Z])", text_lower):
            positive_count += 1

    for word in _NEGATIVE_WORDS:
        if re.search(r"(?<![a-zA-Z])" + re.escape(word) + r"(?![a-zA-Z])", text_lower):
            negative_count += 1

    if positive_count > negative_count:
        sentiment = "positive"
    elif negative_count > positive_count:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    log.debug(
        f"تحليل المشاعر: إيجابي={positive_count} سلبي={negative_count} → {sentiment}"
    )
    return sentiment


def _determine_consequence(action: str) -> str:
    """تحديد نتيجة الفعل: إيجابية / سلبية / محايدة."""
    _POSITIVE_ACTIONS = {
        "bought", "approved", "launched", "listed", "partnered", "burned",
    }
    _NEGATIVE_ACTIONS = {
        "hacked", "rejected", "banned", "delisted", "sold",
    }
    if action in _POSITIVE_ACTIONS:
        return "positive"
    elif action in _NEGATIVE_ACTIONS:
        return "negative"
    return "neutral"


def _find_nearest(
    text_lower: str,
    anchor_pos: int,
    candidates: list,
    get_pos_fn,
    max_distance: int = 150,
) -> object:
    """
    إيجاد أقرب مرشح إلى نقطة مرجعية في النص.
    يستخدم لحاقظ الكيانات مع الأرقام والأفعال في نفس الجملة.
    """
    best = None
    best_dist = max_distance
    for c in candidates:
        pos = get_pos_fn(c, text_lower)
        if pos >= 0:
            dist = abs(pos - anchor_pos)
            if dist < best_dist:
                best_dist = dist
                best = c
    return best


# ═══════════════════════════════════════════════════════════════
# 🧩 تركيب الحقائق — تجميع الكيانات والأفعال والأرقام
# ═══════════════════════════════════════════════════════════════

def _build_facts(
    title: str,
    text: str,
    coins: List[str],
    companies: List[str],
    people: List[str],
    actions: List[str],
    dollar_amounts: List[Tuple[float, str]],
    coin_amounts_raw: List[Tuple[float, str, str]],
) -> List[Fact]:
    """
    تجميع كل البيانات المستخرجة في كائنات Fact.

    الاستراتيجية:
    - لكل كيان (شركة/شخص): ابحث عن أقرب فعل، عملة، ومبلغ.
    - للعملات بدون كيان: أنشئ حقائق بسيطة.
    - لا ننشئ حقيقية مكررة — كل كيان يظهر مرة واحدة فقط (أهم حقيقة).

    مثال:
      "BlackRock bought 400 BTC worth $48M"
      → Fact(entity="BlackRock", action="bought", asset="BTC",
             amount=400, amount_display="400 BTC", value_usd=48000000)
    """
    facts: List[Fact] = []
    used_coins: Set[str] = set()
    used_amounts: Set[str] = set()
    combined = f"{title} {text}".strip()
    combined_lower = combined.lower()

    # --- دوال مساعدة للبحث عن المواقع ---
    def _entity_pos(name: str, txt: str) -> int:
        return txt.find(name.lower())

    def _coin_pos(coin: str, txt: str) -> int:
        # البحث عن الرمز الكبير مع حدود الكلمة
        for variant in [coin, coin.lower()]:
            idx = txt.find(variant)
            if idx >= 0:
                return idx
        return -1

    def _amount_pos(amount_tuple, txt: str) -> int:
        # amount_tuple هو (value, display_string)
        return txt.find(amount_tuple[1].lower())

    def _coin_amt_pos(coin_amt: Tuple, txt: str) -> int:
        return txt.find(coin_amt[2].lower())

    all_entities = companies + people

    # ─── 1. حقائق الكيانات (شركات + أشخاص) ───
    for entity in all_entities:
        entity_pos = _entity_pos(entity, combined_lower)
        if entity_pos < 0:
            continue

        fact = Fact(entity=entity, consequence="neutral")

        # أقرب فعل
        if actions:
            # ابحث عن كل فعل في النص وأختر الأقرب
            best_action = None
            best_dist = 150
            for action in actions:
                # البحث عن أي كلمة من هذا الفعل في النص
                for pattern, label in _ACTION_PATTERNS:
                    if label == action:
                        m = pattern.search(combined)
                        if m:
                            dist = abs(m.start() - entity_pos)
                            if dist < best_dist:
                                best_dist = dist
                                best_action = action
            fact.action = best_action or actions[0]
            fact.consequence = _determine_consequence(fact.action)

        # أقرب عملة
        best_coin = _find_nearest(
            combined_lower, entity_pos, coins, _coin_pos
        )
        if best_coin:
            fact.asset = best_coin
            used_coins.add(best_coin)

        # أقرب مبلغ بالدولار
        best_dollar = _find_nearest(
            combined_lower, entity_pos, dollar_amounts,
            _amount_pos
        )
        if best_dollar:
            fact.value_usd = best_dollar[0]
            fact.amount_display = best_dollar[1]
            used_amounts.add(best_dollar[1])

        # أقرب كمية عملة
        best_ca = _find_nearest(
            combined_lower, entity_pos, coin_amounts_raw,
            _coin_amt_pos
        )
        if best_ca:
            fact.amount = best_ca[0]
            if not fact.asset:
                fact.asset = best_ca[1]
            if not fact.amount_display:
                fact.amount_display = best_ca[2]
            used_amounts.add(best_ca[2])

        # أقرب منصة (بورصة أخرى)
        for company in companies:
            if company.lower() != entity.lower():
                c_pos = _entity_pos(company, combined_lower)
                if 0 <= c_pos < 150 and abs(c_pos - entity_pos) < 150:
                    fact.platform = company
                    break

        facts.append(fact)
        log.debug(
            f"حقيقة: entity={fact.entity} action={fact.action} "
            f"asset={fact.asset} amount={fact.amount} "
            f"value_usd={fact.value_usd} display={fact.amount_display}"
        )

    # ─── 2. حقائق العملات بدون كيان ───
    remaining_coins = [c for c in coins if c not in used_coins]

    for coin in remaining_coins:
        if actions:
            best_action = actions[0] if actions else ""
            fact = Fact(
                entity="",
                action=best_action,
                asset=coin,
                consequence=_determine_consequence(best_action),
            )
            # أقرب مبلغ
            coin_pos = _coin_pos(coin, combined_lower)
            if coin_pos >= 0:
                best_dollar = _find_nearest(
                    combined_lower, coin_pos, dollar_amounts, _amount_pos
                )
                if best_dollar:
                    fact.value_usd = best_dollar[0]
                    fact.amount_display = best_dollar[1]
                best_ca = _find_nearest(
                    combined_lower, coin_pos, coin_amounts_raw, _coin_amt_pos
                )
                if best_ca:
                    fact.amount = best_ca[0]
                    if not fact.amount_display:
                        fact.amount_display = best_ca[2]
            facts.append(fact)
            log.debug(
                f"حقيقة (عملة): asset={coin} action={best_action} "
                f"value_usd={fact.value_usd}"
            )
        elif dollar_amounts or coin_amounts_raw:
            fact = Fact(asset=coin, consequence="neutral")
            if dollar_amounts:
                fact.value_usd = dollar_amounts[0][0]
                fact.amount_display = dollar_amounts[0][1]
            if coin_amounts_raw:
                fact.amount = coin_amounts_raw[0][0]
                if not fact.amount_display:
                    fact.amount_display = coin_amounts_raw[0][2]
            facts.append(fact)

    # ─── 3. حقائق المبالغ المتبقية بدون كيان ───
    remaining_dollars = [
        (v, d) for v, d in dollar_amounts if d not in used_amounts
    ]
    remaining_ca = [
        ca for ca in coin_amounts_raw if ca[2] not in used_amounts
    ]

    if remaining_dollars and not facts:
        for value, display in remaining_dollars[:2]:  # حد أقصى 2
            facts.append(Fact(
                entity=companies[0] if companies else "",
                asset=coins[0] if coins else "",
                value_usd=value,
                amount_display=display,
                consequence="neutral",
            ))

    if remaining_ca and not any(f.amount > 0 for f in facts):
        for ca in remaining_ca[:2]:
            facts.append(Fact(
                entity=companies[0] if companies else "",
                asset=ca[1],
                amount=ca[0],
                amount_display=ca[2],
                consequence="neutral",
            ))

    return facts


# ═══════════════════════════════════════════════════════════════
# 🚀 نقطة الدخول الرئيسية
# ═══════════════════════════════════════════════════════════════

def extract_facts(text: str, title: str = "") -> ExtractedFacts:
    """
    الدالة الرئيسية — تستخرج كل الحقائق من نص الخبر.

    المعاملات:
        text:  نص الخبر الكامل (الملخص أو المحتوى)
        title: عنوان الخبر (يحصل على أولوية أعلى)

    يعيد:
        ExtractedFacts — كائن يحتوي كل الحقائق المستخرجة.

    الاستراتيجية:
        1. فحص العنوان أولاً (أولوية أعلى في ترتيب المطابقة)
        2. فحص النص الكامل (يشمل العنوان مرة واحدة — بدون تكرار)
        3. البحث عن العملات، الشركات، الأشخاص، الأفعال
        4. استخراج المبالغ المالية
        5. تحليل المشاعر
        6. تجميع كل شيء في حقائق منظمة
    """
    if not text and not title:
        log.warning("extract_facts استُدعيت بنص فارغ")
        return ExtractedFacts()

    # النص الكامل — العنوان مرة واحدة + النص (بدون مضاعفة)
    full_text = f"{title} {text}".strip() if title else text.strip()

    log.debug(f"═══ بدء استخراج الحقائق ═══")
    log.debug(f"العنوان: {title[:80]}")
    log.debug(f"النص: {text[:120]}")

    # ─── 1. العملات ───
    coins = _scan_for_coins(full_text)
    log.debug(f"العملات: {coins}")

    # ─── 2. الشركات ───
    companies = _scan_for_companies(full_text)
    log.debug(f"الشركات: {companies}")

    # ─── 3. الأشخاص ───
    people = _scan_for_people(full_text)
    log.debug(f"الأشخاص: {people}")

    # ─── 4. المبالغ المالية ───
    dollar_amounts = _extract_dollar_amounts(full_text)
    log.debug(f"مبالغ الدولار: {dollar_amounts}")

    coin_amounts_raw = _extract_coin_amounts(full_text)
    log.debug(f"كميات العملات: {coin_amounts_raw}")

    word_amounts = _extract_word_amounts(full_text)
    log.debug(f"مبالغ بالكلمات: {word_amounts}")

    # ─── 5. الأفعال ───
    actions = _scan_for_actions(full_text)
    log.debug(f"الأفعال: {actions}")

    # ─── 6. المشاعر ───
    sentiment = _compute_sentiment(full_text)
    log.debug(f"المشاعر: {sentiment}")

    # ─── 7. تجميع الحقائق ───
    facts = _build_facts(
        title=title,
        text=text,
        coins=coins,
        companies=companies,
        people=people,
        actions=actions,
        dollar_amounts=dollar_amounts,
        coin_amounts_raw=coin_amounts_raw,
    )

    # ─── 8. أرقام عامة ───
    all_numbers: List[str] = []
    for _, display in dollar_amounts:
        all_numbers.append(display)
    for ca in coin_amounts_raw:
        all_numbers.append(ca[2])
    for _, display in word_amounts:
        all_numbers.append(display)

    # ─── 9. الكيانات الرئيسية (فريدة) ───
    main_entities: List[str] = []
    seen_entities: Set[str] = set()
    for entity in companies + people:
        if entity not in seen_entities:
            main_entities.append(entity)
            seen_entities.add(entity)

    # ─── 10. هل توجد بيانات مالية؟ ───
    has_financial_data = bool(dollar_amounts or coin_amounts_raw or word_amounts)

    # ─── بناء النتيجة ───
    result = ExtractedFacts(
        facts=facts,
        main_entities=main_entities,
        coins=coins,
        companies=companies,
        people=people,
        numbers=all_numbers,
        has_financial_data=has_financial_data,
        sentiment=sentiment,
    )

    log.info(
        f"✅ استخراج الحقائق: "
        f"{len(facts)} حقيقة | {len(coins)} عملات | "
        f"{len(companies)} شركات | {len(people)} أشخاص | "
        f"مالية={has_financial_data} | مشاعر={sentiment}"
    )

    return result


# ═══════════════════════════════════════════════════════════════
# 🧪 اختبار سريع — عند التشغيل المباشر: python fact_extractor.py
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_cases = [
        {
            "name": "شراء مع كميات",
            "title": "BlackRock bought 400 BTC worth $48M",
            "text": "BlackRock has accumulated 400 Bitcoin worth approximately $48 million as part of its strategy.",
            "expected_coins": ["BTC"],
            "expected_companies": ["BlackRock"],
            "expected_actions": ["bought"],
            "expected_sentiment": "positive",
        },
        {
            "name": "اختراق",
            "title": "Binance was hacked for $570M",
            "text": "A security breach on Binance resulted in $570 million being drained from hot wallets.",
            "expected_coins": [],
            "expected_companies": ["Binance"],
            "expected_actions": ["hacked"],
            "expected_sentiment": "negative",
        },
        {
            "name": "موافقة SEC",
            "title": "SEC approved Bitcoin ETF",
            "text": "The Securities and Exchange Commission gave approval to multiple spot Bitcoin ETF applications.",
            "expected_coins": ["BTC"],
            "expected_companies": ["SEC"],
            "expected_actions": ["approved"],
            "expected_sentiment": "positive",
        },
        {
            "name": "شخص + عملة + شراء",
            "title": "Michael Saylor buys 12,000 BTC",
            "text": "MicroStrategy CEO Michael Saylor announced the purchase of 12,000 Bitcoin worth $700M.",
            "expected_coins": ["BTC"],
            "expected_companies": ["MicroStrategy"],
            "expected_people": ["Michael Saylor"],
            "expected_actions": ["bought"],
            "expected_sentiment": "positive",
        },
        {
            "name": "بيع مع كميات",
            "title": "Ethereum Foundation sells $100M worth of ETH",
            "text": "The foundation sold 25,000 ETH valued at $100 million in a series of transactions.",
            "expected_coins": ["ETH"],
            "expected_companies": [],
            "expected_actions": ["sold"],
            "expected_sentiment": "negative",
        },
        {
            "name": "حظر وعملة",
            "title": "China bans cryptocurrency trading",
            "text": "Chinese regulators have banned all cryptocurrency trading activities, causing Bitcoin to plunge.",
            "expected_coins": ["BTC"],
            "expected_companies": [],
            "expected_actions": ["banned"],
            "expected_sentiment": "negative",
        },
        {
            "name": "شراكة",
            "title": "Coinbase partners with BlackRock for custody",
            "text": "Coinbase announced a strategic partnership with BlackRock to provide custody services.",
            "expected_coins": [],
            "expected_companies": ["BlackRock", "Coinbase"],
            "expected_actions": ["partnered"],
            "expected_sentiment": "positive",
        },
        {
            "name": "إدراج عملة",
            "title": "Binance listed PEPE for trading",
            "text": "PEPE is now listed on Binance with multiple trading pairs available.",
            "expected_coins": ["PEPE"],
            "expected_companies": ["Binance"],
            "expected_actions": ["listed"],
            "expected_sentiment": "positive",
        },
        {
            "name": "مبلغ بسيط بدون فعل",
            "title": "Bitcoin reaches $150K",
            "text": "The price of Bitcoin has surpassed the $150,000 mark for the first time.",
            "expected_coins": ["BTC"],
            "expected_companies": [],
            "expected_actions": [],
            "expected_sentiment": "positive",
        },
    ]

    print("=" * 60)
    print("🧪 اختبار مستخرج الحقائق — Whale News Bot v3")
    print("=" * 60)

    passed = 0
    failed = 0

    for i, tc in enumerate(test_cases, 1):
        print(f"\n--- اختبار {i}: {tc['name']} ---")
        print(f"العنوان: {tc['title']}")

        result = extract_facts(tc["text"], tc["title"])

        print(f"  العملات: {result.coins}")
        print(f"  الشركات: {result.companies}")
        print(f"  الأشخاص: {result.people}")
        print(f"  الكيانات: {result.main_entities}")
        print(f"  الأفعال: {[f.action for f in result.facts]}")
        print(f"  المشاعر: {result.sentiment}")
        print(f"  مالية: {result.has_financial_data}")
        print(f"  الأرقام: {result.numbers}")
        for f in result.facts:
            print(
                f"    → Fact(entity={f.entity!r}, action={f.action!r}, "
                f"asset={f.asset!r}, amount={f.amount}, "
                f"value_usd={f.value_usd}, display={f.amount_display!r})"
            )

        ok = True
        checks = []

        if tc["expected_coins"]:
            if not all(c in result.coins for c in tc["expected_coins"]):
                missing = [c for c in tc["expected_coins"] if c not in result.coins]
                checks.append(f"عملات مفقودة: {missing}")
                ok = False

        if tc.get("expected_companies"):
            if not all(c in result.companies for c in tc["expected_companies"]):
                missing = [c for c in tc["expected_companies"] if c not in result.companies]
                checks.append(f"شركات مفقودة: {missing}")
                ok = False

        if tc.get("expected_people"):
            if not all(p in result.people for p in tc["expected_people"]):
                missing = [p for p in tc["expected_people"] if p not in result.people]
                checks.append(f"أشخاص مفقودين: {missing}")
                ok = False

        if tc["expected_actions"]:
            fact_actions = [f.action for f in result.facts if f.action]
            if not all(a in fact_actions for a in tc["expected_actions"]):
                missing = [a for a in tc["expected_actions"] if a not in fact_actions]
                checks.append(f"أفعال مفقودة: {missing}")
                ok = False

        if tc["expected_sentiment"]:
            if result.sentiment != tc["expected_sentiment"]:
                checks.append(
                    f"مشاعر: متوقع={tc['expected_sentiment']} حصلنا={result.sentiment}"
                )
                ok = False

        if ok:
            print("  ✅ نجاح")
            passed += 1
        else:
            print(f"  ❌ فشل: {' | '.join(checks)}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"النتيجة: ✅ {passed} نجح | ❌ {failed} فشل | من {len(test_cases)} اختبار")
    print("=" * 60)
