"""
🌐 Whale News Bot v2.0 - نظام الترجمة المتقدم
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ترجمة async مع caching ذكي، verification، و fallback متعدد
"""

import os, re, hashlib, time, asyncio
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass

import aiohttp

from config import log, BotConfig


# ═══════════════════════════════════════════════════════════
# 💾 Translation Cache (ذاكرة دائمة + ذاكرة مؤقتة)
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
            placeholder = f"§§{counter:03d}§§"
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

    # تنظيف أي placeholders متبقية
    result = re.sub(r"§§\d{3}§§", "", result)
    return result


# ═══════════════════════════════════════════════════════════
# 🤖 Gemini Translation (Async)
# ═══════════════════════════════════════════════════════════
class GeminiTranslator:
    """مترجم Gemini مع إدارة النماذج"""

    _STEP1_PROMPT = """Extract ONLY the verified facts from the following text.

Ignore:
- duplicated text
- duplicated titles
- RSS formatting
- hashtags
- opinions
- predictions
- broken machine translation
- grammar mistakes

Return ONLY a bullet list of unique facts. Each bullet must be one verified fact.
Do not add any explanation. Do not translate. Do not summarize.
Use the same language as the source for each fact.
If the source is English, keep facts in English. If Arabic, keep in Arabic.

Example output:
• Bitcoin reached a seven-week high.
• Spot ETFs recorded inflows.
• Investors expect regulatory clarity in Q3."""

    _SYSTEM_PROMPT = """You are a senior Arabic cryptocurrency news editor.

Your job is NOT to translate.

Your job is to understand the source news, extract only the verified facts, and rewrite the news from scratch in fluent, natural Arabic suitable for immediate publication on a professional Telegram crypto news channel.

The source may contain:
- English or Arabic.
- Poor machine translation.
- Mixed Arabic and English.
- Duplicated titles or paragraphs.
- Incorrect hashtags.
- RSS artifacts.
- Grammar mistakes.

Ignore all of these problems and reconstruct the news from its factual meaning only.

Rules:

1. Never translate literally.

2. Never preserve awkward wording from the source.

3. Rewrite the news completely in professional Arabic.

4. Remove duplicated titles and duplicated sentences.

5. Remove RSS artifacts such as:
   - Read more
   - First appeared on...
   - Originally published...
   - Source:
   - Via:

6. If the source contains machine translation errors, ignore the wording completely and infer the intended meaning only from the surrounding factual context.

7. Never invent facts.

8. Never speculate.

9. Never exaggerate.

10. Preserve all:
- prices
- percentages
- dates
- company names
- blockchain names
- protocol names
- token symbols

11. Keep official names in English:
Bitcoin
Ethereum
Solana
Coinbase
BlackRock
Franklin Templeton
Binance

12. Translate technical terms naturally.

Examples:

killer app -> \u0623\u0628\u0631\u0632 \u062a\u0637\u0628\u064a\u0642
game changer -> \u0646\u0642\u0644\u0629 \u0646\u0648\u0639\u064a\u0629
validator -> \u0645\u062f\u0642\u0642
mainnet -> \u0627\u0644\u0634\u0628\u0643\u0629 \u0627\u0644\u0631\u0626\u064a\u0633\u064a\u0629
stablecoin -> \u0639\u0645\u0644\u0629 \u0645\u0633\u062a\u0642\u0631\u0629
AI Agent -> \u0648\u0643\u064a\u0644 \u0630\u0643\u0627\u0621 \u0627\u0635\u0637\u0646\u0627\u0639\u064a
Agentic AI -> \u0627\u0644\u0630\u0643\u0627\u0621 \u0627\u0644\u0627\u0635\u0637\u0646\u0627\u0639\u064a \u0627\u0644\u0648\u0643\u064a\u0644\u064a
exploit -> \u0627\u0633\u062a\u063a\u0644\u0627\u0644 \u062b\u063a\u0631\u0629
hack -> \u0627\u062e\u062a\u0631\u0627\u0642
upgrade -> \u062a\u0631\u0642\u064a\u0629
tokenization -> \u062a\u0631\u0645\u064a\u0632 \u0627\u0644\u0623\u0635\u0648\u0644
inflows -> \u062a\u062f\u0641\u0642\u0627\u062a \u062f\u0627\u062e\u0644\u0629
outflows -> \u062a\u062f\u0641\u0642\u0627\u062a \u062e\u0627\u0631\u062c\u0629

13. Never use these AI phrases:

- \u0641\u064a \u062e\u0637\u0648\u0629 \u062a\u0639\u0643\u0633...
- \u062e\u0644\u0627\u0644 \u0627\u0644\u0641\u062a\u0631\u0629 \u0627\u0644\u062d\u0627\u0644\u064a\u0629...
- \u0645\u0645\u0627 \u0639\u0632\u0632 \u062b\u0642\u0629 \u0627\u0644\u0645\u0633\u062a\u062b\u0645\u0631\u064a\u0646...
- \u0648\u0633\u0637 \u062a\u0632\u0627\u064a\u062f \u0627\u0644\u0627\u0647\u062a\u0645\u0627\u0645...
- \u0627\u0644\u062a\u0637\u0628\u064a\u0642 \u0627\u0644\u0642\u0627\u062a\u0644...
- \u063a\u064a\u0651\u0631 \u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0644\u0639\u0628\u0629...

14. Validate hashtags.

- Never trust hashtags from the source.
- Generate a hashtag only if the news is clearly related to a cryptocurrency.
- If the news is about a company, regulation, ETF, lawsuit, security incident, or macro event, do not generate any hashtag.

15. The first sentence must immediately state the main news.

16. Write between 40 and 80 words.

17. If the body repeats the headline, rewrite it with new factual information instead of repeating the same idea.

18. Never repeat the headline inside the body.

19. Remove duplicated news, duplicated headlines and duplicated paragraphs.

20. If the article is only a price prediction or technical analysis, clearly present it as an analyst's view rather than as a confirmed event.

21. Remove generic filler such as:
- وسط ترقب الأسواق
- مما يعزز الزخم
- وسط تداولات متقلبة
unless supported by explicit facts.

22. Never output duplicate hashtags.

23. Output exactly one headline and one body.

24. If the source contains two versions of the same news, keep only the better one.

25. Every sentence must introduce new information. If it doesn't, delete it.

Output format exactly:

🔵 <Headline>

<News paragraph>

<Hashtag if applicable, otherwise leave blank>

Return ONLY the final news."""

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
        """ترجمة باستخدام Gemini - نظام خطوتين"""
        await self._init()
        if not self._models:
            return None

        import google.generativeai as genai

        for model_name in self._models:
            try:
                # === المرحلة الأولى: استخراج الحقائق ===
                step1_model = genai.GenerativeModel(model_name, system_instruction=self._STEP1_PROMPT)
                step1_response = await asyncio.to_thread(
                    step1_model.generate_content,
                    text,
                    generation_config={
                        "temperature": 0.1,
                        "top_p": 0.8,
                        "top_k": 40,
                        "max_output_tokens": 500,
                    }
                )
                if not step1_response or not step1_response.text:
                    log.info(f"⏭️ Gemini ({model_name}) step 1 failed: no response")
                    continue

                facts = step1_response.text.strip().strip('"\'`')
                if not facts or len(facts) < 10:
                    log.info(f"⏭️ Gemini ({model_name}) step 1: facts too short ({len(facts)} chars)")
                    continue

                log.info(f"✅ Gemini ({model_name}) step 1: extracted {len(facts)} chars of facts")

                # === المرحلة الثانية: كتابة الخبر من الحقائق ===
                step2_prompt = self._build_prompt(facts, missing_names)
                step2_model = genai.GenerativeModel(model_name, system_instruction=self._SYSTEM_PROMPT)
                step2_response = await asyncio.to_thread(
                    step2_model.generate_content,
                    step2_prompt,
                    generation_config={
                        "temperature": 0.2 if missing_names else 0.3,
                        "top_p": 0.8,
                        "top_k": 40,
                        "max_output_tokens": 1000,
                    }
                )
                if step2_response and step2_response.text:
                    result = step2_response.text.strip().strip('"\'`')
                    title, body = self._parse_output(result)
                    if title:
                        log.info(f"✅ Gemini ({model_name}): step 2 translation success")
                        return title, body
            except Exception as e:
                log.info(f"⏭️ Gemini ({model_name}) failed: {str(e)[:60]}")
                continue

        return None

    def _build_prompt(self, facts: str, missing_names: Optional[List[str]] = None) -> str:
        """بناء البرومبت للمرحلة الثانية من الحقائق المستخرجة"""
        prompt = f"Write one professional Arabic crypto news article from these facts.\n\nDo not repeat any fact.\n"
        if missing_names:
            prompt += f"\n🔴 تنبيه: هذه الأسماء اختفت في المحاولة السابقة: {', '.join(missing_names)}. يجب أن تظهر كلها.\n"
        prompt += f"\nFacts:\n\n{facts}"
        return prompt

    def _parse_output(self, text: str) -> Tuple[Optional[str], str]:
        """استخراج العنوان والخبر من التنسيق الجديد أو القديم"""
        if not text:
            return None, ""

        # التنسيق الجديد: 🔵 <عنوان>\n\n<فقرة>\n\n#<ticker>
        blue_match = re.split(r'\n\n+', text.strip(), maxsplit=2)
        if blue_match and blue_match[0].startswith("\U0001f535"):
            title = blue_match[0].replace("\U0001f535", "").strip().lstrip(" -")
            body = ""
            if len(blue_match) > 1:
                # الفقرة هي الجزء الثاني (قد يحتوي #ticker في نهايته)
                paragraph = blue_match[1].strip()
                # إزالة سطر #ticker إن وُجد
                ticker_match = re.match(r'^(.+?)\n*#.*$', paragraph, re.DOTALL)
                body = ticker_match.group(1).strip() if ticker_match else paragraph
            if title and len(title) > 3:
                return title.strip(" .,،:؛-"), body.strip(" .,،:؛-")

        # التنسيق القديم: العنوان:...\nالخبر:...
        parts = re.split(r'\n\s*الخبر\s*:\s*', text, maxsplit=1)
        if len(parts) == 2:
            header = parts[0].strip()
            body = parts[1].strip()
            title_match = re.split(r'\n\s*العنوان\s*:\s*', header, maxsplit=1)
            if len(title_match) == 2:
                title = title_match[1].strip()
            else:
                title = header

            title = title.strip(" .,،:؛-")
            body = body.strip(" .,،:؛-")

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
                            {"role": "system", "content": "You are a senior Arabic crypto news editor. NOT a translator. Rewrite from meaning, not wording. Remove duplicates, RSS artifacts (Read more, Source, Via), broken translation, incorrect hashtags. Never translate literally. Never invent facts, speculate, or exaggerate. Preserve prices, percentages, dates, names. Keep official names in English. Terms: killer app=أبرز تطبيق, game changer=نقلة نوعية, validator=مدقق, mainnet=الشبكة الرئيسية, stablecoin=عملة مستقرة, AI Agent=وكيل ذكاء اصطناعي, exploit=استغلال ثغرة, hack=اختراق, upgrade=ترقية, inflows=تدفقات داخلة, outflows=تدفقات خارجة, ETF=صندوق متداول, staking=الرهن, DeFi=التمويل اللامركزي. BANNED phrases: في خطوة تعكس, خلال الفترة الحالية, مما عزز ثقة المستثمرين, وسط تزايد الاهتمام, التطبيق القاتل, غيّر قواعد اللعبة, وسط ترقب الأسواق, مما يعزز الزخم, وسط تداولات متقلبة. HASHTAGS: never trust source - generate only if news is about a specific cryptocurrency. No hashtag for company/regulation/ETF/lawsuit/macro news. No duplicate hashtags. If body repeats headline, rewrite with new facts. Output exactly one headline and one body. If two versions of same news, keep better one. Every sentence must add new info. Price predictions must be marked as analyst view. 40-80 words. Start with main event. Format:\n\n🔵 <Arabic headline>\n\n<News paragraph>\n\n#<Ticker if applicable, else leave blank>"},
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
                            {"role": "system", "content": "You are a senior Arabic crypto news editor. NOT a translator. Rewrite from meaning, not wording. Remove duplicates, RSS artifacts (Read more, Source, Via), broken translation, incorrect hashtags. Never translate literally. Never invent facts, speculate, or exaggerate. Preserve prices, percentages, dates, names. Keep official names in English. Terms: killer app=أبرز تطبيق, game changer=نقلة نوعية, validator=مدقق, mainnet=الشبكة الرئيسية, stablecoin=عملة مستقرة, AI Agent=وكيل ذكاء اصطناعي, exploit=استغلال ثغرة, hack=اختراق, upgrade=ترقية, inflows=تدفقات داخلة, outflows=تدفقات خارجة, ETF=صندوق متداول, staking=الرهن, DeFi=التمويل اللامركزي. BANNED phrases: في خطوة تعكس, خلال الفترة الحالية, مما عزز ثقة المستثمرين, وسط تزايد الاهتمام, التطبيق القاتل, غيّر قواعد اللعبة, وسط ترقب الأسواق, مما يعزز الزخم, وسط تداولات متقلبة. HASHTAGS: never trust source - generate only if news is about a specific cryptocurrency. No hashtag for company/regulation/ETF/lawsuit/macro news. No duplicate hashtags. If body repeats headline, rewrite with new facts. Output exactly one headline and one body. If two versions of same news, keep better one. Every sentence must add new info. Price predictions must be marked as analyst view. 40-80 words. Start with main event. Format:\n\n🔵 <Arabic headline>\n\n<News paragraph>\n\n#<Ticker if applicable, else leave blank>"},
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
        bad_endings = ("على", "في", "من", "إلى", "عن", "مع", "حتى", "خلال",
                       "بعد", "قبل", "بين", "ضد", "عبر", "نحو", "لدى", "بسبب",
                       "✉️", "...", "،", ":")
        if trimmed.endswith(bad_endings):
            return False
        if len(trimmed) >= 250 and not re.search(r'[.!؟?!]$', trimmed):
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
            log.info(f"   📋 Entities: {entities}")

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
                        log.warning(f"   🔄 Gemini retry — missing: {missing}")
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

        log.warning("   ❌ All translation methods failed")
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
