"""
🌐 Whale News Bot v2.0 - نظام الترجمة المتقدم
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ترجمة async مع caching ذكي، verification، و fallback متعدد
"""

import os, re, hashlib, time, asyncio
from typing import Optional, Tuple, Dict, List

import aiohttp

from config import log, BotConfig


# ═══════════════════════════════════════════════════════════
# 💾 Translation Cache (ذاكرة مؤقتة)
# ═══════════════════════════════════════════════════════════
class TranslationCache:
    """Cache ذكي للترجمة مع TTL"""

    def __init__(self, ttl: int = 86400):  # 24 ساعة
        self._memory: Dict[str, Tuple[str, float]] = {}
        self._ttl = ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            if key in self._memory:
                value, timestamp = self._memory[key]
                if time.time() - timestamp < self._ttl:
                    return value
                del self._memory[key]
            return None

    async def set(self, key: str, value: str):
        async with self._lock:
            self._memory[key] = (value, time.time())
            # تنظيف القديم
            if len(self._memory) > 1000:
                now = time.time()
                old_keys = [k for k, (_, ts) in self._memory.items() if now - ts > self._ttl]
                for k in old_keys:
                    del self._memory[k]

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

    # دمج القائمتين
    all_terms = []
    for term, trans in GLOSSARY_AR.items():
        all_terms.append((term, trans))
    for term in CRITICAL_NAMES:
        if term not in GLOSSARY_AR:
            all_terms.append((term, None))

    all_terms.sort(key=lambda x: len(x[0]), reverse=True)

    for term, trans in all_terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        match = pattern.search(protected)
        if match:
            placeholder = f"\u00a7\u00a7{counter:03d}\u00a7\u00a7"
            protected = pattern.sub(placeholder, protected, count=1)
            restore_map[placeholder] = (match.group(0), trans)
            counter += 1

    return protected, restore_map


def _restore_entities(text: str, restore_map: Dict) -> str:
    """استعادة الكيانات بعد الترجمة"""
    if not restore_map:
        return text

    result = text
    # ترتيب عكسي لتجنب التداخل
    sorted_placeholders = sorted(restore_map.keys(), key=lambda x: int(x[2:5]), reverse=True)

    for placeholder in sorted_placeholders:
        original, trans = restore_map[placeholder]
        replacement = trans if trans else original

        # أنماط متعددة للبحث
        num = int(placeholder[2:5])
        patterns = [
            re.escape(placeholder),
            re.escape(f"\u00a7\u00a7{num}\u00a7\u00a7"),
            re.escape(f"\u00a7 {num} \u00a7"),
            re.escape(f"({num})"),
            re.escape(f"[{num}]"),
            re.escape(f"\u00ab{num}\u00bb"),
        ]

        for pat in patterns:
            new_result = re.sub(pat, replacement, result, flags=re.IGNORECASE)
            if new_result != result:
                result = new_result
                break

    # تنظيف أي placeholders متبقية
    result = re.sub(r"\u00a7\u00a7\d{3}\u00a7\u00a7", "", result)
    return result


# ═══════════════════════════════════════════════════════════
# 🤖 Gemini Translation (Async)
# ═══════════════════════════════════════════════════════════
class GeminiTranslator:
    """مترجم Gemini مع إدارة النماذج"""

    _SYSTEM_PROMPT = """أنت محرر صحفي عربي محترف متخصص في أخبار العملات الرقمية.

قواعد صارمة:
1. العربية الفصحى السهلة والواضحة فقط
2. إعادة صياغة احترافية وليست ترجمة حرفية
3. حافظ على جميع المعلومات والأرقام دون إضافة
4. اترك أسماء العملات والشركات بالإنجليزية: Bitcoin, Ethereum, Binance, SEC, ETF
5. ترجم المصطلحات: hack=اختراق, exploit=ثغرة, crash=انهيار, surge=قفزة
6. تجاهل اسم المصدر في النهاية
7. لا إيموجي أو مقدمات
8. أكمل كل جملة
9. العنوان: جذاب ومختصر (≤ 90 حرف)
10. الخبر: 50-120 كلمة

التنسيق المطلوب:
العنوان:
...

الخبر:
..."""

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
                        model = genai.GenerativeModel(model_name, system_instruction=self._SYSTEM_PROMPT)
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
                    # محاولة اكتشاف تلقائي
                    try:
                        models_list = list(genai.list_models())
                        for m in models_list:
                            name = m if isinstance(m, str) else getattr(m, 'name', str(m))
                            if name and ("flash" in name.lower() or "pro" in name.lower()):
                                try:
                                    model = genai.GenerativeModel(name, system_instruction=self._SYSTEM_PROMPT)
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
                self._initialized = True  # لا نعيد المحاولة

    async def translate(self, text: str, missing_names: Optional[List[str]] = None) -> Optional[Tuple[str, str]]:
        """ترجمة باستخدام Gemini"""
        await self._init()
        if not self._models:
            return None

        # بناء الـ prompt
        prompt = self._build_prompt(text, missing_names)

        import google.generativeai as genai

        for model_name in self._models:
            try:
                model = genai.GenerativeModel(model_name, system_instruction=self._SYSTEM_PROMPT)
                response = await asyncio.to_thread(
                    model.generate_content,
                    prompt,
                    generation_config={
                        "temperature": 0.2 if missing_names else 0.3,
                        "top_p": 0.8,
                        "top_k": 40,
                        "max_output_tokens": 1000,
                    }
                )
                if response and response.text:
                    # 🔧 إصلاح: إزالة علامات الاقتباس المتداخلة
                    result = response.text.strip()
                    result = result.strip('"').strip("'").strip("`")
                    title, body = self._parse_output(result)
                    if title:
                        log.info(f"✅ Gemini ({model_name}): translation success")
                        return title, body
            except Exception as e:
                log.info(f"⏭️ Gemini ({model_name}) failed: {str(e)[:60]}")
                continue

        return None

    def _build_prompt(self, text: str, missing_names: Optional[List[str]] = None) -> str:
        text_len = len(text)
        sent_count = "2" if text_len < 150 else "2-3" if text_len < 400 else "3-4"

        prompt = f"""أعد صياغة الخبر التالي بالعربية الفصحى بأسلوب صحفي احترافي.

الشروط:
- اكتب من {sent_count} جمل حسب طول الخبر
- حافظ على جميع أسماء العملات والشركات والأرقام
- لا تحذف أي اسم عملة أو شركة
- لا تستبدل الأسماء بكلمات عامة
- لا تضف معلومات غير موجودة
- أخرج النص العربي النهائي فقط
"""
        if missing_names:
            prompt += f"""
🔴 تنبيه: هذه الأسماء اختفت في المحاولة السابقة: {', '.join(missing_names)}. يجب أن تظهر كلها.
"""

        prompt += f"""
الخبر:

{text}"""
        return prompt

    def _parse_output(self, text: str) -> Tuple[Optional[str], str]:
        """استخراج العنوان والخبر — 🔧 إصلاح: raw strings صحيحة"""
        if not text:
            return None, ""

        # 🔧 إصلاح حرج: استخدام raw strings مع \n الحقيقي (ليس newline حرفي)
        # البحث عن "الخبر:" مع فاصل سطر
        parts = re.split(r'\n\s*الخبر\s*:\s*', text, maxsplit=1)
        if len(parts) == 2:
            header = parts[0].strip()
            body = parts[1].strip()
            # البحث عن "العنوان:" مع فاصل سطر
            title_match = re.split(r'\n\s*العنوان\s*:\s*', header, maxsplit=1)
            if len(title_match) == 2:
                title = title_match[1].strip()
            else:
                title = header

            title = title.strip(" .,\u060c:;\u061b-")
            body = body.strip(" .,\u060c:;\u061b-")

            if len(title) > 3 and (len(body) > 10 or not body):
                return title, body

        return text, ""


# ═══════════════════════════════════════════════════════════
# 🔄 Fallback Translators
# ═══════════════════════════════════════════════════════════
class GroqTranslator:
    """Fallback: Groq API"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def translate(self, text: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": "أعد صياغة الخبر الإنجليزي بالعربية الفصحى بأسلوب صحفي. حافظ على الأسماء الإنجليزية."},
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
                        result = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        if result and len(result) > 5:
                            log.info("✅ Groq translation success")
                            return result
        except Exception as e:
            log.warning(f"Groq translation failed: {e}")
        return None


class OpenRouterTranslator:
    """Fallback: OpenRouter"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def translate(self, text: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={
                        "model": "qwen/qwen-2.5-72b-instruct",
                        "messages": [
                            {"role": "system", "content": "أعد صياغة الخبر الإنجليزي بالعربية الفصحى. حافظ على الأسماء الإنجليزية."},
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
                        result = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        if result and len(result) > 5:
                            log.info("✅ OpenRouter translation success")
                            return result
        except Exception as e:
            log.warning(f"OpenRouter translation failed: {e}")
        return None


class GoogleTranslator:
    """Fallback المجاني: Google Translate"""

    async def translate(self, text: str) -> Optional[str]:
        try:
            # حماية الكيانات
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

                    # استعادة الكيانات
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
    """مدير الترجمة الموحد"""

    def __init__(self, config: BotConfig):
        self.config = config
        self.gemini = GeminiTranslator(config.GEMINI_API_KEY) if config.GEMINI_API_KEY else None
        self.groq = GroqTranslator(config.GROQ_API_KEY) if config.GROQ_API_KEY else None
        self.openrouter = OpenRouterTranslator(config.OPENROUTER_API_KEY) if config.OPENROUTER_API_KEY else None
        self.google = GoogleTranslator()

    def _extract_entities(self, text: str) -> List[str]:
        """استخراج الكيانات للتحقق"""
        text_lower = text.lower()
        found = []
        for name in sorted(CRITICAL_NAMES, key=len, reverse=True):
            if name in text_lower and name not in found:
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

    def _is_quality_good(self, text: str) -> bool:
        """التحقق من جودة النص العربي"""
        if not text or len(text) < 5:
            return False

        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        if len(text) > 20 and arabic_chars / len(text) < 0.25:
            log.warning(f"Low Arabic ratio: {arabic_chars/len(text)*100:.0f}%")
            return False

        # فحص كلمات إنجليزية مشبوهة
        english_words = re.findall(r'[a-zA-Z]{4,}', text)
        allowed = {"Bitcoin", "Ethereum", "Binance", "Coinbase", "USDT", "USDC",
                   "Solana", "Cardano", "Ripple", "BlackRock", "MicroStrategy",
                   "SEC", "ETF", "DeFi", "NFT", "Web3"}
        suspicious = [w for w in english_words if w not in allowed]
        if suspicious:
            log.warning(f"Suspicious English words: {suspicious[:5]}")
            return False

        return True

    def _is_complete(self, text: str) -> bool:
        """التحقق من اكتمال النص"""
        if not text:
            return False
        trimmed = text.strip()
        bad_endings = ("\u0639\u0644\u0649", "\u0641\u064a", "\u0645\u0646", "\u0625\u0644\u0649", "\u0639\u0646", "\u0645\u0639", "\u062d\u062a\u0649", "\u062e\u0644\u0627\u0644",
                       "\u0628\u0639\u062f", "\u0642\u0628\u0644", "\u0628\u064a\u0646", "\u0636\u062f", "\u0639\u0628\u0631", "\u0646\u062d\u0648", "\u0644\u062f\u0649", "\u0628\u0633\u0628\u0628",
                       "\u2709\ufe0f", "...", "\u060c", ":")
        if trimmed.endswith(bad_endings):
            return False
        if len(trimmed) >= 250 and not re.search(r'[.!?\u061f?!]$', trimmed):
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

    async def translate(self, text: str, force: bool = False) -> Optional[str]:
        """ترجمة النص - النظام الكامل"""
        if not text or len(text) < 3:
            return text

        text = self._truncate(text)
        cache_key = translation_cache._hash_key(text)

        if not force:
            cached = await translation_cache.get(cache_key)
            if cached:
                return cached

        # حماية الكيانات
        protected_text, restore_map = _protect_entities(text)
        entities = self._extract_entities(text)
        if entities:
            log.info(f"   \U0001f4cb Entities: {entities}")

        # ═══ الطبقة 1: Gemini ═══
        if self.gemini:
            result = await self.gemini.translate(protected_text)
            if result:
                title, body = result
                title = _restore_entities(title, restore_map)
                body = _restore_entities(body, restore_map) if body else ""

                if self._is_quality_good(title):
                    check_text = title + " " + body
                    ok, missing = self._verify_entities(text, check_text)

                    if not ok:
                        log.warning(f"   \U0001f504 Gemini retry \u2014 missing: {missing}")
                        retry = await self.gemini.translate(protected_text, missing_names=missing)
                        if retry:
                            title, body = retry
                            title = _restore_entities(title, restore_map)
                            body = _restore_entities(body, restore_map) if body else ""
                            if self._is_quality_good(title):
                                final = title if not body else title + "\n" + body
                                await translation_cache.set(cache_key, final)
                                return final
                    else:
                        final = title if not body else title + "\n" + body
                        await translation_cache.set(cache_key, final)
                        return final

        # ═══ الطبقة 2: Groq ═══
        if self.groq:
            result = await self.groq.translate(protected_text)
            if result:
                result = _restore_entities(result, restore_map)
                if self._is_quality_good(result):
                    await translation_cache.set(cache_key, result)
                    return result

        # ═══ الطبقة 3: OpenRouter ═══
        if self.openrouter:
            result = await self.openrouter.translate(protected_text)
            if result:
                result = _restore_entities(result, restore_map)
                if self._is_quality_good(result):
                    await translation_cache.set(cache_key, result)
                    return result

        # ═══ الطبقة 4: Google Translate ═══
        result = await self.google.translate(text)  # يحتوي على حماية داخلية
        if result:
            result = _restore_entities(result, restore_map)
            arabic_chars = sum(1 for c in result if '\u0600' <= c <= '\u06FF')
            if len(result) > 20 and arabic_chars / len(result) >= 0.15:
                await translation_cache.set(cache_key, result)
                return result

        log.warning("   \u274c All translation methods failed")
        return None

    async def translate_item(self, item) -> None:
        """ترجمة عنصر خبر"""
        title = getattr(item, 'title', '') or item.get('title', '')
        summary = getattr(item, 'summary', '') or item.get('summary', '')

        title_ar = await self.translate(title)
        if title_ar:
            if hasattr(item, 'title_ar'):
                item.title_ar = title_ar
            else:
                item['title_ar'] = title_ar

        if summary:
            summary_ar = await self.translate(summary)
            if summary_ar:
                if hasattr(item, 'summary_ar'):
                    item.summary_ar = summary_ar
                else:
                    item['summary_ar'] = summary_ar


# ═══════════════════════════════════════════════════════════
# 📊 ETF Flow Report (Async — مُعاد من النسخة القديمة)
# ═══════════════════════════════════════════════════════════
_ETF_FLOW_REPORT_PROMPT = """أنت محلل مالي متخصص في صناديق ETF الخاصة بالعملات الرقمية.

ستستلم بيانات صافي التدفقات اليومية بعد إغلاق جلسة التداول الأمريكية.

المطلوب:

1. أنشئ تقريراً عربياً احترافياً ومختصراً.
2. ابدأ بعنوان مناسب يوضح أن التقرير خاص بإغلاق الجلسة.
3. اعرض جميع الصناديق بنفس الترتيب الوارد في البيانات.
4. لا تغيّر أي رقم أو قيمة.
5. احتفظ بالإشارات (+) و(-).
6. استخدم:
   \u2197\ufe0f للتدفقات الموجبة.
   \U0001f4c9 للتدفقات السالبة.
   \u2796 عندما تكون القيمة صفر.
7. في النهاية اكتب فقرة قصيرة بعنوان:
   \U0001f4ca الخلاصة
8. يجب أن تعتمد الخلاصة على الأرقام فقط دون أي توقعات أو نصائح استثمارية.
9. إذا كانت معظم التدفقات موجبة فاذكر أن الجلسة شهدت تدفقات إيجابية.
10. إذا كانت معظمها سالبة فاذكر أن الجلسة شهدت ضغوط بيع.
11. إذا كانت متباينة فاذكر أن التدفقات كانت مختلطة.
12. إذا كانت جميع القيم صفراً فاذكر أنه لم تُسجل تدفقات تُذكر.
13. لا تخترع أي معلومة غير موجودة.
14. لا تذكر أسعار العملات أو توقعات السوق.
15. أخرج التقرير النهائي فقط دون أي مقدمات أو تعليقات."""


async def generate_etf_flow_report(etf_data: str, config_obj: BotConfig) -> Optional[str]:
    """يولّد تقرير تدفقات ETF اليومي باستخدام LLM (async)
    etf_data: نص يحتوي بيانات التدفقات
    Returns: التقرير العربي أو None إذا فشل
    """
    if not etf_data:
        return None

    user_prompt = f"بيانات التدفقات:\n\n{etf_data}\n\nأعد التقرير:"

    # تجربة Gemini أولاً
    if config_obj.GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=config_obj.GEMINI_API_KEY)

            model_names = [
                "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest",
                "gemini-2.5-pro", "gemini-2.0-pro",
            ]

            for model_name in model_names:
                try:
                    model = genai.GenerativeModel(model_name, system_instruction=_ETF_FLOW_REPORT_PROMPT)
                    response = await asyncio.to_thread(
                        model.generate_content,
                        _ETF_FLOW_REPORT_PROMPT + "\n\n" + user_prompt,
                        generation_config={
                            "temperature": 0.2, "top_p": 0.8, "top_k": 40,
                            "max_output_tokens": 1200,
                        }
                    )
                    if response and response.text:
                        result = response.text.strip().strip('"\'`')
                        if len(result) > 20:
                            log.info("   \u2705 ETF report generated (Gemini)")
                            return result
                except Exception as e:
                    log.info(f"   \u23ed\ufe0f Gemini ETF report failed: {str(e)[:60]}")
                    continue
        except Exception as e:
            log.warning(f"Gemini ETF init err: {e}")

    # Fallback: Groq (async)
    if config_obj.GROQ_API_KEY:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": _ETF_FLOW_REPORT_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1200,
                    },
                    headers={
                        "Authorization": f"Bearer {config_obj.GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        if result and len(result) > 20:
                            log.info("   \u2705 ETF report generated (Groq)")
                            return result
        except Exception as e:
            log.warning(f"Groq ETF report err: {e}")

    return None


# ═══════════════════════════════════════════════════════════
# 🌍 Translation Utilities
# ═══════════════════════════════════════════════════════════
SOURCES_AR = {
    "CoinDesk": "كوين ديسك",
    "Cointelegraph": "كوين تيليغراف",
    "Decrypt": "ديكريبت",
    "BeInCrypto": "بي إن كريبتو",
    "Crypto.News": "كريبتو نيوز",
    "Blockworks": "بلوك وركس",
    "Bitcoinist": "بيتكوينيست",
    "Federal Reserve": "الاحتياطي الفيدرالي",
    "Google News - Crypto": "أخبار كريبتو",
    "Google News - ETF": "أخبار ETF",
    "Google News AR - Bitcoin": "أخبار بيتكوين",
    "Google News AR - Fed": "أخبار الفيدرالي",
}

COINS_AR = {
    "BTC": "بيتكوين", "ETH": "إيثيريوم", "SOL": "سولانا",
    "XRP": "ريبل", "ADA": "كاردانو", "DOGE": "دوجكوين",
    "AVAX": "أفالانش", "MATIC": "بوليغون", "LINK": "تشين لينك",
    "DOT": "بولكادوت", "LTC": "لايتكوين", "BNB": "بينانس كوين",
    "USDT": "تيثر", "APT": "أبتوس", "ARB": "أربيترم",
    "OP": "أوبتيميزم", "SUI": "سوي", "SEI": "سي", "TON": "تونكوين",
}


def translate_source_name(source: str) -> str:
    return SOURCES_AR.get(source, source)


def translate_coin_name(symbol: str) -> str:
    return f"{symbol} ({COINS_AR.get(symbol, symbol)})"