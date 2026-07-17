import os as _os, re, hashlib, time, logging
import requests

from config import log

# ═══════════════════════════════════════════════════════════
# نظام الترجمة التلقائية
# ═══════════════════════════════════════════════════════════
_translation_cache = {}

# قاموس المصطلحات الاقتصادية للترجمة الأفضل
ECONOMIC_TERMS = {
    "bitcoin": "بيتكوين",
    "ethereum": "إيثيريوم",
    "cryptocurrency": "العملات الرقمية",
    "crypto": "الكريبتو",
    "blockchain": "البلوكتشين",
    # "federal reserve": تمت إزالته (غير كريبتو)
    "approval": "الموافقة",
    "hack": "اختراق",
    "exploit": "ثغرة أمنية",
    "stablecoin": "العملة المستقرة",
    "defi": "تمويل لامركزي",
    "nft": "الرموز غير القابلة للاستبدال",
    "exchange": "بورصة",
    "trading": "التداول",
    "market": "السوق",
    "bullish": "صعودي",
    "bearish": "هبوطي",
    "rally": "ارتفاع",
    "plunge": "انهيار",
    "surge": "قفزة",
    "dump": "تصحيح حاد",
    "pump": "ضخ",
    "whale": "حيتان",
    "liquidation": "تصفية",
    "leverage": "الرافعة المالية",
    "futures": "العقود الآجلة",
    "spot": "الفوري",
    "mining": "التعدين",
    "wallet": "محفظة",
    "token": "رمز",
    "coin": "عملة",
    "altcoin": "العملات البديلة",
    "memecoin": "عملات الميم",
    "staking": "التحصيص",
    "yield": "العائد",
    "treasury": "الخزانة",
    # إضافات لتحسين جودة الترجمة
    "coinbase": "كوين بيس",
    "binance": "بايننس",
    "tether": "تيثر",
    "usdt": "USDT",
    "usdc": "USDC",
    "ripple": "ريبل",
    "xrp": "XRP",
    "solana": "سولانا",
    "cardano": "كاردانو",
    "avalanche": "أفالانش",
    "polygon": "بوليجون",
    "polkadot": "بولكادوت",
    "chainlink": "تشين لينك",
    "microstrategy": "مايكروستراتيجي",
    "blackrock": "بلاك روك",
    "grayscale": "جرايسكيل",
    "fidelity": "فيديليتي",
    "smart wallet": "المحفظة الذكية",
    "smart contract": "العقد الذكي",
    "upgrade": "تحديث",
    "rollout": "إطلاق",
    "launch": "إطلاق",
    "release": "إصدار",
    "target": "يستهدف",
    "targets": "يستهدف",
    "ux": "تجربة المستخدم",
    "ui": "واجهة المستخدم",
    "multi-chain": "متعدد السلاسل",
    "cross-chain": "عبر السلاسل",
    "layer 2": "الطبقة الثانية",
    "l2": "الطبقة الثانية",
    "scaling": "التوسع",
    "verification": "التحقق",
    "verify": "التحقق",
    "user experience": "تجربة المستخدم",
    "mainnet": "الشبكة الرئيسية",
    "testnet": "شبكة الاختبار",
    "protocol": "البروتوكول",
    "decentralized": "لامركزي",
    "decentralization": "اللامركزية",
    "institutional": "مؤسسي",
    "inflows": "تدفقات داخلة",
    "outflows": "تدفقات خارجة",
    "fund flow": "تدفق الأموال",
    "halving": "النصفية",
    "bull market": "السوق الصاعد",
    "bear market": "السوق الهابط",
    "correction": "تصحيح",
    "crash": "انهيار",
    "all-time high": "أعلى مستوى تاريخي",
    "ath": "أعلى مستوى تاريخي",
    "support": "الدعم",
    "resistance": "المقاومة",
    "volume": "حجم التداول",
    "volatility": "التقلب",
    "sentiment": "التوجه",
    # "fomc", "cpi", "ppi": تمت إزالتها (مصطلحات اقتصادية عامة)
}

# قاموس الاستثناءات: أسماء لا تُترجم (تبقى بالإنجليزية)
# يشمل: أسماء العملات، الشركات، البروتوكولات، الرموز، التوكنات
# الهدف: الحفاظ على السياق المعروف للمستخدمين
TRANSLATION_EXCEPTIONS = [
    # أمثلة شائعة تُترجم خطأً
    "sauce", "saucer", "saucerswap",
    "shiba inu", "shib", "doge", "dogelon mars",
    "pepe", "wojak", "chad",
    # أسماء العملات الرقمية (تبقى بالإنجليزية)
    "bitcoin", "btc", "ethereum", "eth", "ether",
    "binance", "bnb", "tether", "ripple", "xrp",
    "solana", "sol", "cardano", "ada", "dogecoin",
    "avalanche", "avax", "polygon", "matic", "polkadot", "dot",
    "chainlink", "link", "litecoin", "ltc",
    "tron", "trx", "eos", "fantom", "ftm",
    "near", "aptos", "apt", "sui", "arbitrum", "arb",
    "optimism", "op", "starknet", "zksync",
    "filecoin", "fil", "arweave", "ar",
    "the graph", "grt", "render", "rndr",
    "theta", "vechain", "vet", "tezos", "xtz",
    "decentraland", "mana", "sandbox", "sand", "axie infinity", "axs",
    "bitcoin cash", "bch", "ethereum classic", "etc",
    # عملات مستقرة (تبقى بالرموز المعروفة)
    "usdt", "usdc", "tether", "busd", "dai", "tusd", "frax",
    # بروتوكولات DeFi ومنصات
    "uniswap", "uni", "pancakeswap", "cake", "sushiswap", "sushi",
    "curve", "crv", "aave", "aave", "compound", "comp",
    "maker", "mkr", "synthetix", "snx", "yearn", "yfi",
    "lido", "ldo", "rocket pool", "rpl",
    # شركات وبورصات (تبقى بالإنجليزية)
    "coinbase", "kraken", "okx", "bybit", "kucoin",
    "huobi", "gemini", "bitfinex", "crypto.com",
    "grayscale", "blackrock", "fidelity",
    # تطبيقات ومحافظ
    "metamask", "trust wallet", "phantom", "rabby",
    # مشاريع AI
    "fetch.ai", "fet", "ocean protocol", "ocean",
    "singularitynet", "agi", "bittensor", "tao",
    # Gaming والميم
    "floki", "bonk", "pepecoin", "memecoin",
    "illuvium", "ilv",
    # أدوات وخدمات
    "etherscan", "blockchain.com", "coingecko", "coinmarketcap",
    # اختصارات تقنية ومالية (تبقى بالإنجليزية)
    "web3", "dao", "ico", "ido", "ieo", "ipo",
    "erc20", "erc721", "bep20", "trc20",
    "etf", "spot etf", "sec", "cftc",
    "defi", "nft", "tvl", "apy", "apr",
    "kyc", "aml",
    "btc.d", "altseason",
    # بروتوكولات وشرائع
    "mica", "fit21", "genius act", "clarity act",
    "19b-4", "s-1",
    # شخصيات (تبقى بالإنجليزية)
    "kevin warsh", "warsh", "saylor", "gensler", "vitalik", "satoshi",
]

# تحويل القائمة إلى set للبحث السريع
_EXC_SET = set(TRANSLATION_EXCEPTIONS)

# قاموس المصطلحات العامة التي تُترجم للعربية
# يشمل: مصطلحات مالية، أحداث، حركات سعرية (وليس أسماء عملات/شركات/بروتوكولات)
GLOSSARY_AR = {
    # مصطلحات تقنية مركبة (أوصاف وليست أسماء)
    "smart wallet": "المحفظة الذكية",
    "smart contract": "العقد الذكي",
    "multi-chain": "متعدد السلاسل",
    "cross-chain": "عبر السلاسل",
    "layer 2": "الطبقة الثانية",
    "layer 1": "الطبقة الأولى",
    "mainnet": "الشبكة الرئيسية",
    "testnet": "شبكة الاختبار",
    "hot wallet": "المحفظة الساخنة",
    "cold wallet": "المحفظة الباردة",
    "hardware wallet": "محفظة الأجهزة",
    "software wallet": "محفظة البرامج",
    # مصطلحات السوق
    "bull market": "السوق الصاعد",
    "bear market": "السوق الهابط",
    "all-time high": "أعلى مستوى تاريخي",
    "all-time low": "أدنى مستوى تاريخي",
    "market cap": "القيمة السوقية",
    "market capitalization": "القيمة السوقية",
    "open interest": "المركزيات المفتوحة",
    "funding rate": "سعر التمويل",
    "long squeeze": "ضغط المراكز الطويلة",
    "short squeeze": "ضغط المراكز القصيرة",
    # مصطلحات تقنية أخرى
    "user experience": "تجربة المستخدم",
    "user interface": "واجهة المستخدم",
    "verification": "التحقق",
    "upgrade": "تحديث",
    "rollout": "إطلاق",
    "launch": "إطلاق",
    "release": "إصدار",
    "roadmap": "خارطة الطريق",
    "whitepaper": "الورقة البيضاء",
    "airdrop": "إيردروب",
    "staking": "التحصيص",
    "mining": "التعدين",
    "halving": "التنصيف",
    "hard fork": "الانقسام الصلب",
    "soft fork": "الانقسام الناعم",
    "the merge": "الدمج",
    "network upgrade": "تحديث الشبكة",
    "protocol upgrade": "تحديث البروتوكول",
    "mainnet launch": "إطلاق الشبكة الرئيسية",
    "mainnet upgrade": "تحديث الشبكة الرئيسية",
    "consensus upgrade": "تحديث الإجماع",
    "smart contract upgrade": "تحديث العقود الذكية",
    "proof of stake": "إثبات الحصة",
    "proof of work": "إثبات العمل",
    "consensus": "الإجماع",
    "validator": "المُتحقق",
    "node": "العقدة",
    "decentralized": "لامركزي",
    "decentralization": "اللامركزية",
    "institutional": "مؤسسي",
    "inflows": "تدفقات داخلة",
    "outflows": "تدفقات خارجة",
    "fund flow": "تدفق الأموال",
    "accumulation": "التراكم",
    # كلمات شائعة في الأخبار
    "etf inflows": "تدفقات صندوق ETF",
    "etf outflows": "تدفقات خارجة من صندوق ETF",
    "spot bitcoin etf": "صندوق Bitcoin الفوري ETF",
    "spot ethereum etf": "صندوق Ethereum الفوري ETF",
    "hack": "اختراق",
    "hacked": "اختراق",
    "exploit": "ثغرة أمنية",
    "stolen": "مُسروق",
    "drained": "تم تصريفه",
    "rug pull": "احتيال",
    "breach": "اختراق أمني",
    "cyberattack": "هجوم سيبراني",
    "vulnerability": "ثغرة",
    "phishing": "تصيد",
    "compromised": "مُخترق",
    "attacker": "المهاجم",
    "hacker": "الهاكر",
    # مصطلحات حركة السعر
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
    "options": "الخيارات",
    "long": "مراكز طويلة",
    "short": "مراكز قصيرة",
    # مصطلحات فك وحرق التوكنات
    "token unlock": "فك توكن",
    "token unlocking": "فك التوكنات",
    "tokens unlocked": "تم فك التوكنات",
    "vesting unlock": "فك الاستحقاق",
    "cliff unlock": "فك التوكنات المتراكمة",
    "unlock schedule": "جدول فك التوكنات",
    "token release": "إطلاق التوكنات",
    "release schedule": "جدول الإطلاق",
    "token burn": "حرق توكن",
    "coin burn": "حرق عملة",
    "burn event": "حدث حرق",
    "buyback and burn": "إعادة الشراء والحرق",
    "deflationary burn": "حرق انكماشي",
    "burn mechanism": "آلية الحرق",
    "burned tokens": "توكنات محروقة",
    # سيولة مؤسسية
    "institutional inflows": "تدفقات مؤسسية داخلة",
    "institutional outflows": "تدفقات مؤسسية خارجة",
    "record inflows": "تدفقات قياسية",
    "record outflows": "تدفقات خارجة قياسية",
    "treasury allocation": "تخصيص الخزانة",
    "bitcoin treasury": "خزانة Bitcoin",  # Bitcoin تبقى بالإنجليزية
    # انهيار وتصحيح
    "flash crash": "انهيار مفاجئ",
    "massive sell-off": "بيع جماعي",
    "capitulation": "استسلام",
    "bloodbath": "مذبحة",
    "meltdown": "انهيار",
    "sharp decline": "انخفاض حاد",
    "steep decline": "انخفاض حاد",
}


def _protect_terms(text):
    """يستبدل المصطلحات المحمية بـ placeholders قبل الترجمة
    يعيد tuple: (النص مع placeholders, قاموس الاستعادة)
    إصلاح: حفظ النص الأصلي (بأحرفه الأصلية) للاستعادة
    إصلاح: استخدام placeholders برموز خاصة لا يترجمها أي محرك
    دمج: نحمي TRANSLATION_EXCEPTIONS (تبقى إنجليزية) + GLOSSARY_AR (تُستبدل بالعربية)
    """
    restore_map = {}  # placeholder → (original_text, arabic_translation_or_None)
    protected_text = text
    counter = 0

    # دمج القائمتين
    all_terms = []
    for term in GLOSSARY_AR.keys():
        all_terms.append((term, "glossary"))
    for term in TRANSLATION_EXCEPTIONS:
        if term not in GLOSSARY_AR:
            all_terms.append((term, "keep"))

    # ترتيب: الأطول أولاً (لتجنب استبدال جزئي)
    all_terms.sort(key=lambda x: len(x[0]), reverse=True)

    for term, term_type in all_terms:
        if term in protected_text.lower():
            # إصلاح: استخدام رموز خاصة «ZZ» + رقم + «ZZ» (Google لا يترجمها)
            placeholder = f"«ZZ{counter}ZZ»"
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            match = pattern.search(protected_text)
            if match:
                original_match = match.group()
                protected_text = pattern.sub(placeholder, protected_text, count=1)
                arabic_translation = GLOSSARY_AR.get(term.lower()) if term_type == "glossary" else None
                restore_map[placeholder] = (original_match, arabic_translation)
                counter += 1
    return protected_text, restore_map


def _restore_terms(translated_text, restore_map):
    """يعيد المصطلحات الأصلية مكان الـ placeholders بعد الترجمة
    إصلاح: الحفاظ على الأحرف الأصلية (USDT بدل usdt)
    دمج: استبدال ذكي - المختصرات تبقى إنجليزية، الأسماء تُستبدل بالعربية
    إصلاح: البحث عن أنماط متعددة للـ placeholder (قد يحرفها المترجم)
    """
    if not restore_map:
        return translated_text
    result = translated_text
    # رتّب الـ placeholders للاستبدال (الأكبر رقماً أولاً لتجنب التداخل)
    sorted_placeholders = sorted(restore_map.keys(),
                                  key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0,
                                  reverse=True)

    for placeholder in sorted_placeholders:
        original, arabic_translation = restore_map[placeholder]
        # ماذا نستبدل به؟
        replacement = arabic_translation if arabic_translation else original

        # استخراج الرقم من الـ placeholder
        match_num = re.search(r'(\d+)', placeholder)
        if not match_num:
            continue
        num_str = match_num.group(1)
        try:
            num = int(num_str)
            arabic_num = "".join("٠١٢٣٤٥٦٧٨٩"[int(d)] for d in str(num))

            # أنماط كثيرة للبحث (Google/NLLB قد يحرف الـ placeholder)
            patterns_to_try = [
                # الشكل الأصلي «ZZ0ZZ»
                re.escape(placeholder),
                # بدون علامات «»
                re.escape(f"ZZ{num_str}ZZ"),
                # بأقواس مربعة [[0]] أو [0]
                re.escape(f"[[{num_str}]]"),
                re.escape(f"[{num_str}]"),
                re.escape(f"[[ {num_str} ]]"),
                re.escape(f"[ {num_str} ]"),
                # بأقواس مدورة ((0))
                re.escape(f"(({num_str}))"),
                # بأرقام عربية
                re.escape(f"«ZZ{arabic_num}ZZ»"),
                re.escape(f"[[{arabic_num}]]"),
                re.escape(f"[[ {arabic_num} ]]"),
                # أنماط مرنة (regex)
                r"«\s*ZZ\s*" + re.escape(num_str) + r"\s*ZZ\s*»",
                r"\[\[\s*" + re.escape(num_str) + r"\s*\]\]",
                r"\[\s*" + re.escape(num_str) + r"\s*\]",
                r"\(\s*" + re.escape(num_str) + r"\s*\)",
                r"«\s*ZZ\s*" + re.escape(arabic_num) + r"\s*ZZ\s*»",
                r"\[\[\s*" + re.escape(arabic_num) + r"\s*\]\]",
                # نمط عام: أي رمز غير حرفي + الرقم + أي رمز غير حرفي
                r"[«\[\(]{1,2}\s*" + re.escape(num_str) + r"\s*[»\]\)]{1,2}",
                r"[«\[\(]{1,2}\s*" + re.escape(arabic_num) + r"\s*[»\]\)]{1,2}",
            ]
            for pat in patterns_to_try:
                new_result = re.sub(pat, replacement, result, flags=re.IGNORECASE)
                if new_result != result:
                    result = new_result
                    break
        except Exception:
            result = re.sub(re.escape(placeholder), replacement, result, flags=re.IGNORECASE)

    # تنظيف شامل لأي placeholders متبقية (أي شكل من الأشكال)
    result = re.sub(r"«\s*ZZ\s*\d+\s*ZZ\s*»", "", result)
    result = re.sub(r"«\s*ZZ\s*[٠-٩]+\s*ZZ\s*»", "", result)
    result = re.sub(r"\[\[\s*\d+\s*\]\]", "", result)
    result = re.sub(r"\[\[\s*[٠-٩]+\s*\]\]", "", result)
    result = re.sub(r"\[\s*\d+\s*\]", "", result)
    result = re.sub(r"\[\s*[٠-٩]+\s*\]", "", result)
    result = re.sub(r"ZZ\s*\d+\s*ZZ", "", result)
    result = re.sub(r"ZZ\s*[٠-٩]+\s*ZZ", "", result)
    return result


_deepl_disabled_until = 0  # تعطيل DeepL مؤقتاً عند فشل الاتصال لتقليل التحذيرات

# ════════════════════════════════════════════════════════════════════
# محرك الترجمة الوحيد: Gemini API (إعادة صياغة صحفية احترافية)
# ════════════════════════════════════════════════════════════════════
# يحوّل الخبر الإنجليزي إلى خبر صحفي عربي احترافي ومختصر
# يحافظ على جميع المعلومات دون إضافة أي معلومات جديدة
# يحافظ على أسماء العملات والشركات بالإنجليزية (Bitcoin, Binance, SEC)
# يتجاهل اسم المصدر إن وُجد في النهاية
# يتجاهل ميتاداتا Reddit ووسوم HTML
_gemini_models = []  # قائمة النماذج المتاحة (Flash + Pro)
_gemini_init_failed = False


def _init_gemini():
    """تهيئة Gemini API - اكتشاف كل النماذج المتاحة (Flash + Pro)"""
    global _gemini_models, _gemini_init_failed
    if _gemini_models or _gemini_init_failed:
        return
    try:
        import google.generativeai as genai
        api_key = (
            _os.environ.get("GEMINI_API_KEY") or
            _os.environ.get("gemini_api_key") or
            _os.environ.get("GEMINI_KEY") or
            _os.environ.get("gemini_key") or
            _os.environ.get("GOOGLE_API_KEY") or
            _os.environ.get("google_api_key") or
            ""
        )
        if not api_key:
            log.warning("⚠️ No Gemini API key found")
            _gemini_init_failed = True
            return
        genai.configure(api_key=api_key)

        system_prompt = (
            "أنت محرر صحفي محترف متخصص في أخبار الكريبتو والأسواق المالية. "
            "مهمتك: إعادة صياغة الأخبار الإنجليزية بالعربية الفصحى بأسلوب صحفي احترافي. "
            "قواعد: (1) العربية الفصحى فقط. (2) أعد الصياغة وليس ترجمة حرفية. "
            "(3) حافظ على جميع المعلومات والأرقام دون إضافة. "
            "(4) اترك أسماء العملات والشركات بالإنجليزية دائماً: Bitcoin, Ethereum, Binance, "
            "USDT, USDC, SEC, ETF, MicroStrategy, BlackRock, Coinbase, Solana, XRP, "
            "Tether, Ripple, Dogecoin, Polkadot, Chainlink, Arbitrum, Uniswap, Aave, "
            "Cardano, Avalanche, Polygon, Near, Aptos, Sui, Base, Optimism, zkSync. "
            "(4.1) لا تحذف اسم عملة أبداً - حتى لو كانت الجملة قصيرة، حافظ على اسم العملة. "
            "(5) ترجم المصطلحات: hack=اختراق, exploit=ثغرة, crash=انهيار, surge=قفزة, "
            "plunge=انهيار, stolen=مُسروقة, drained=تم تصريفها, token unlock=فك توكن, "
            "token burn=حرق توكن, hard fork=انقسام صلب. "
            "(6) تجاهل اسم المصدر في النهاية. (7) تجاهل ميتاداتا Reddit. "
            "(8) لا إيموجي أو مقدمات. (9) أكمل كل جملة. (10) أعد النص العربي فقط."
        )

        # قائمة كل النماذج المرشحة (Flash أولاً لأنه أسرع، ثم Pro)
        candidate_models = [
            "gemini-2.5-flash", "gemini-2.5-flash-preview-05-20",
            "gemini-2.0-flash", "gemini-2.0-flash-exp", "gemini-2.0-flash-001",
            "gemini-1.5-flash-latest", "gemini-1.5-flash", "gemini-1.5-flash-001",
            "gemini-flash-latest",
            "gemini-2.5-pro", "gemini-2.5-pro-preview-05-06",
            "gemini-2.0-pro", "gemini-2.0-pro-exp",
            "gemini-1.5-pro-latest", "gemini-1.5-pro", "gemini-1.5-pro-001",
            "gemini-pro-latest",
        ]
        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name, system_instruction=system_prompt
                )
                test_resp = model.generate_content(
                    "test", generation_config={"max_output_tokens": 5}
                )
                if test_resp and test_resp.text:
                    _gemini_models.append(model)
                    log.info(f"✅ Gemini ready: {model_name}")
            except Exception:
                continue

        # اكتشاف تلقائي عبر list_models
        # الإصدارات الجديدة من google-generativeai تعيد strings من list_models()
        # وليس كائنات تحتوي على .name و .supported_generation_methods
        if not _gemini_models:
            try:
                models_list = list(genai.list_models())
                for m in models_list:
                    try:
                        # التعامل مع كلا الإصدارين: str أو كائن
                        if isinstance(m, str):
                            model_name = m
                        else:
                            model_name = getattr(m, 'name', str(m))

                        if not model_name:
                            continue
                        # تخطي النماذج التي ليست flash أو pro
                        name_lower = model_name.lower()
                        if not ("flash" in name_lower or "pro" in name_lower):
                            continue

                        model = genai.GenerativeModel(
                            model_name=model_name, system_instruction=system_prompt
                        )
                        test_resp = model.generate_content(
                            "test", generation_config={"max_output_tokens": 5}
                        )
                        if test_resp and test_resp.text:
                            _gemini_models.append(model)
                            log.info(f"✅ Gemini ready (discovered): {model_name}")
                            if len(_gemini_models) >= 3:
                                break
                    except Exception:
                        continue
            except Exception as e:
                log.warning(f"Model listing failed: {e}")

        if not _gemini_models:
            log.warning("⚠️ No working Gemini model found")
            _gemini_init_failed = True
    except Exception as e:
        log.warning(f"⚠️ Gemini init failed: {e}")
        _gemini_init_failed = True


# ═══════════════════════════════════════════════════════════
# برومبت الترجمة الموحد (يُستخدم في Gemini)
# ═══════════════════════════════════════════════════════════
_TRANSLATION_SYSTEM_PROMPT = """أنت محرر صحفي عربي محترف ومتخصص في أخبار العملات الرقمية والأسواق المالية.

مهمتك ليست الترجمة الحرفية، بل إعادة صياغة النص المترجم ليصبح خبرًا عربيًا طبيعيًا وسلسًا مع الحفاظ الكامل على المعنى.

اتبع القواعد التالية بدقة:

- لا تضف أي معلومات غير موجودة في النص الأصلي.
- لا تحذف أي معلومة مهمة.
- استخدم العربية الفصحى السهلة والواضحة.
- تجنب الأسلوب الآلي أو الترجمة الحرفية.
- استخدم المصطلحات العربية الشائعة في مجال العملات الرقمية.
- احتفظ بأسماء العملات والرموز كما هي (Bitcoin, Ethereum, BTC, ETH...).
- اجعل العنوان جذابًا ومختصرًا (لا يتجاوز 90 حرفًا).
- اجعل متن الخبر بين 50 و120 كلمة.
- استبدل العبارات الحرفية بصياغات صحفية طبيعية.
- إذا احتوى النص على أرقام أو نسب مئوية أو أسعار أو تواريخ، فلا تغيرها إطلاقًا.
- لا تضف مقدمات أو تعليقات أو آراء أو تحذيرات.
- لا تستخدم عبارات مثل "وفقًا للنص" أو "تشير الترجمة".
- أخرج النتيجة بهذا التنسيق فقط:

العنوان:
...

الخبر:
..."""

# ═══════════════════════════════════════════════════════════
# برومبت تقرير تدفقات صناديق ETF اليومية
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
   ↗️ للتدفقات الموجبة.
   📉 للتدفقات السالبة.
   ➖ عندما تكون القيمة صفر.
7. في النهاية اكتب فقرة قصيرة بعنوان:
   📊 الخلاصة
8. يجب أن تعتمد الخلاصة على الأرقام فقط دون أي توقعات أو نصائح استثمارية.
9. إذا كانت معظم التدفقات موجبة فاذكر أن الجلسة شهدت تدفقات إيجابية.
10. إذا كانت معظمها سالبة فاذكر أن الجلسة شهدت ضغوط بيع.
11. إذا كانت متباينة فاذكر أن التدفقات كانت مختلطة.
12. إذا كانت جميع القيم صفراً فاذكر أنه لم تُسجل تدفقات تُذكر.
13. لا تخترع أي معلومة غير موجودة.
14. لا تذكر أسعار العملات أو توقعات السوق.
15. أخرج التقرير النهائي فقط دون أي مقدمات أو تعليقات."""


def generate_etf_flow_report(etf_data):
    """يولّد تقرير تدفقات ETF اليومي باستخدام LLM
    etf_data: نص يحتوي بيانات التدفقات (يُمرر كما هو للنموذج)
    Returns: التقرير العربي أو None إذا فشل
    """
    if not etf_data:
        return None
    user_prompt = f"بيانات التدفقات:\n\n{etf_data}\n\nأعد التقرير:"

    # تجربة Gemini أولاً
    if not _gemini_init_failed:
        _init_gemini()
        if _gemini_models:
            for model in _gemini_models:
                try:
                    response = model.generate_content(
                        _ETF_FLOW_REPORT_PROMPT + "\n\n" + user_prompt,
                        generation_config={
                            "temperature": 0.2, "top_p": 0.8, "top_k": 40,
                            "max_output_tokens": 1200,
                        }
                    )
                    if response and response.text:
                        result = response.text.strip().strip('"\'`')
                        if len(result) > 20:
                            log.info("   ✅ ETF report generated (Gemini)")
                            return result
                except Exception as e:
                    log.info(f"   ⏭️ Gemini ETF report failed: {str(e)[:60]}")
                    continue

    # Fallback: Groq
    try:
        api_key = _os.environ.get("GROQ_API_KEY") or _os.environ.get("groq_api_key") or ""
        if api_key:
            r = requests.post(
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
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                result = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if result and len(result) > 20:
                    log.info("   ✅ ETF report generated (Groq)")
                    return result
    except Exception as e:
        log.warning(f"Groq ETF report err: {e}")

    return None


# أسماء يجب التحقق من وجودها بعد الترجمة (بالأحرف الأصلية)
_CRITICAL_NAMES = [
    # عملات
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "ripple",
    "cardano", "ada", "dogecoin", "doge", "avalanche", "avax", "polkadot", "dot",
    "chainlink", "link", "polygon", "matic", "litecoin", "ltc", "tron", "trx",
    "arbitrum", "arb", "optimism", "op", "aptos", "apt", "sui", "sei",
    "near", "fantom", "ftm", "cosmos", "atom", "uniswap", "aave",
    # عملات مستقرة
    "usdt", "usdc", "tether", "dai", "busd",
    # شركات وبورصات
    "binance", "coinbase", "kraken", "bybit", "okx", "kucoin",
    "blackrock", "microstrategy", "grayscale", "fidelity", "van eck",
    "franklin templeton", "ark invest", "robinhood", "gemini",
    # جهات تنظيمية
    "sec", "cftc", "gensler",
    # شخصيات
    "satoshi", "vitalik", "saylor", "buterin", "zhao", "cz",
    "musk", "dorsey", "armstrong", "hoskinson",
    # بروتوكولات/شبكات
    "ethereum", "bitcoin", "solana",
    # ETF
    "etf", "spot etf",
    # مصطلحات
    "defi", "nft", "web3", "dao",
]


def _extract_entities(text):
    """يستخرج أسماء الكيانات (عملات، شركات، شخصيات...) من النص
    Returns: list of names found (بالأحرف الأصلية من النص)
    """
    text_lower = text.lower()
    found = []
    # ترتيب: الأطول أولاً (لتجنب استخراج "eth" بدل "ethereum")
    for name in sorted(_CRITICAL_NAMES, key=len, reverse=True):
        if name in text_lower and name not in found:
            found.append(name)
    return found


def _verify_entities(original_text, translated_text):
    """يتحقق أن أسماء الكيانات من النص الأصلي موجودة في الترجمة
    Returns: (is_ok, missing_names)
    """
    if not translated_text:
        return False, ["(empty)"]
    entities = _extract_entities(original_text)
    if not entities:
        return True, []  # لا أسماء حرجة = لا فحص
    translated_lower = translated_text.lower()
    missing = [n for n in entities if n not in translated_lower]
    return len(missing) == 0, missing


def _build_user_prompt(text, missing_names=None):
    """بناء user prompt ذكي حسب طول الخبر وأسماء مفقودة"""
    text_len = len(text)
    # عدد الجمل مرن حسب طول الخبر
    if text_len < 150:
        sent_count = "2"
    elif text_len < 400:
        sent_count = "2-3"
    else:
        sent_count = "3-4"

    prompt = (
        f"أعد صياغة الخبر التالي بالعربية الفصحى بأسلوب صحفي احترافي.\n\n"
        f"الشروط:\n\n"
        f"- اكتب من {sent_count} جمل حسب طول الخبر، مع الحفاظ الكامل على جميع أسماء العملات والشركات والأرقام. "
        f"إذا احتاج الخبر إلى جملة إضافية للحفاظ على المعلومات فلا تختصره.\n"
        f"- حافظ على جميع المعلومات المهمة.\n"
        f"- لا تحذف أي اسم عملة أو شركة أو بروتوكول أو شخصية أو مؤسسة.\n"
        f"- لا تستبدل الأسماء بكلمات مثل \"الشركة\" أو \"المشروع\".\n"
        f"- حافظ على جميع الأرقام والنسب المئوية كما هي.\n"
        f"- لا تضف أي معلومات غير موجودة.\n"
        f"- إذا كان الخبر يحتوي على عدة أسماء فيجب ذكرها جميعاً.\n"
        f"- لا تستخدم لغة تسويقية أو مبالغات.\n"
        f"- أخرج النص العربي النهائي فقط.\n"
    )

    # إذا كانت هذه إعادة محاولة: أدرج الأسماء المفقودة صراحة
    if missing_names:
        names_str = ", ".join(missing_names)
        prompt += (
            f"\n🔴 تنبيه مهم: في المحاولة السابقة اختفت هذه الأسماء من الترجمة: "
            f"({names_str}). "
            f"يجب أن تظهر كلها بالإنجليزية كما هي في النص الأصلي.\n"
        )

    prompt += f"\nالخبر:\n\n{text}"
    return prompt


def _translate_with_google(text):
    """بديل مجاني: Google Translate عبر endpoint غير رسمي
    لا يحتاج مفتاح API ولا ينفد — لكنه ترجمة حرفية وليست صياغة صحفية
    Returns: النص المترجم أو None
    """
    try:
        # حماية الأسماء الإنجليزية المهمة قبل الترجمة
        # نستبدلها بعلامات مؤقتة لمنع ترجمتها
        protected = {}
        counter = [0]
        # أسماء طويلة أولاً (لتجنب استبدال جزئي)
        protected_names = sorted(_CRITICAL_NAMES, key=len, reverse=True)

        def protect_match(m):
            key = f"__PROT{counter[0]}__"
            counter[0] += 1
            protected[key] = m.group(0)
            return key

        # حماية الأسماء في النص (كلمات كاملة فقط، case-insensitive)
        text_protected = text
        for name in protected_names:
            pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
            text_protected = pattern.sub(protect_match, text_protected)

        # استدعاء Google Translate
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "ar",
            "dt": "t",
            "q": text_protected,
        }
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            log.info(f"   ⏭️ Google Translate failed: HTTP {r.status_code}")
            return None

        data = r.json()
        # Google Translate يعيد قائمة متداخلة: [[["translated", "original", ...], ...], ...]
        translated_parts = []
        if data and isinstance(data, list) and len(data) > 0:
            for item in data[0]:
                if isinstance(item, list) and len(item) > 0:
                    translated_parts.append(item[0])
        result = "".join(translated_parts).strip()

        if not result or len(result) < 3:
            return None

        # استعادة الأسماء المحمية
        for key, original in protected.items():
            result = result.replace(key, original)

        log.info("   ✅ Google Translate succeeded")
        return result

    except Exception as e:
        log.warning(f"Google Translate err: {e}")
        return None


def _parse_title_body(gemini_output):
    """استخراج العنوان والخبر من نتيجة Gemini
    Gemini يُخرج التنسيق:
        العنوان:
        ...

        الخبر:
        ...
    Returns: (title, body) أو (النص كاملاً, "") لو لم يجد التنسيق
    """
    if not gemini_output:
        return None, None

    text = gemini_output.strip()

    # البحث عن "العنوان:" متبوعاً بمحتوى
    title = None
    body = None

    # نمط 1: العنوان: ... \n\n الخبر: ...
    m = re.split(r'\n\s*الخبر\s*:\s*', text, maxsplit=1)
    if len(m) == 2:
        header_part = m[0].strip()
        body = m[1].strip()
        # استخراج العنوان من الجزء الأول
        m2 = re.split(r'\n\s*العنوان\s*:\s*', header_part, maxsplit=1)
        if len(m2) == 2:
            title = m2[1].strip()
        else:
            title = header_part

    if title and body:
        # تنظيف
        title = title.strip(" .,،:؛-")
        body = body.strip(" .,،:؛-")
        if len(title) > 3 and len(body) > 10:
            return title, body

    return text, ""


def _translate_with_gemini(text, missing_names=None):
    """إعادة صياغة الخبر بالعربية - تجربة كل نماذج Gemini المتاحة
    Returns: (title_ar, body_ar) أو (None, None)
    missing_names: أسماء مفقودة من محاولة سابقة (لإعادة المحاولة مع تذكير)
    """
    if _gemini_init_failed:
        return None, None
    _init_gemini()
    if not _gemini_models:
        return None, None
    user_prompt = _build_user_prompt(text, missing_names)
    prompt = _TRANSLATION_SYSTEM_PROMPT + "\n\n" + user_prompt
    # تجربة كل النماذج المتاحة حتى ينجح واحد
    for i, model in enumerate(_gemini_models):
        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.2 if missing_names else 0.3,
                    "top_p": 0.8, "top_k": 40,
                    "max_output_tokens": 1000,
                }
            )
            if response and response.text:
                result = response.text.strip().strip('"\'`')
                for prefix in ["النص العربي:", "النص العربي المعاد صياغته:", "الترجمة:", "الصياغة:"]:
                    if result.startswith(prefix):
                        result = result[len(prefix):].strip()
                if len(result) > 5:
                    # استخراج العنوان والخبر من تنسيق Gemini
                    title, body = _parse_title_body(result)
                    if title:
                        log.info(f"   ✅ Gemini model #{i+1} succeeded (title+body)")
                        return title, body
                    else:
                        # لم يلتزم بالتنسيق لكن النص موجود
                        log.info(f"   ✅ Gemini model #{i+1} succeeded (flat)")
                        return result, ""
        except Exception as e:
            log.info(f"   ⏭️ Gemini model #{i+1} failed: {str(e)[:80]}")
            continue
    return None, None


def _translate_with_groq(text, missing_names=None):
    """Fallback 1: Groq API (Llama 3.3 70B) - مجاني، سريع جداً
    missing_names: أسماء مفقودة من محاولة سابقة
    """
    try:
        api_key = (
            _os.environ.get("GROQ_API_KEY") or
            _os.environ.get("groq_api_key") or
            ""
        )
        if not api_key:
            return None
        url = "https://api.groq.com/openai/v1/chat/completions"
        system_prompt = _TRANSLATION_SYSTEM_PROMPT
        user_prompt = _build_user_prompt(text, missing_names)
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2 if missing_names else 0.3,
            "max_tokens": 800,
        }
        r = requests.post(
            url, json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=30
        )
        if r.status_code == 200:
            data = r.json()
            result = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if result and len(result) > 5:
                # إزالة علامات اقتباس
                result = result.strip('"\'`')
                log.info("   ✅ Groq (Llama 3.3 70B) succeeded")
                return result
        else:
            log.info(f"   ⏭️ Groq failed: HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"Groq err: {e}")
    return None


def _translate_with_openrouter(text, missing_names=None):
    """Fallback 2: OpenRouter (Qwen 2.5 72B) - مجاني
    missing_names: أسماء مفقودة من محاولة سابقة
    """
    try:
        api_key = (
            _os.environ.get("OPENROUTER_API_KEY") or
            _os.environ.get("openrouter_api_key") or
            ""
        )
        if not api_key:
            return None
        url = "https://openrouter.ai/api/v1/chat/completions"
        system_prompt = _TRANSLATION_SYSTEM_PROMPT
        user_prompt = _build_user_prompt(text, missing_names)
        payload = {
            "model": "qwen/qwen-2.5-72b-instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2 if missing_names else 0.3,
            "max_tokens": 800,
        }
        r = requests.post(
            url, json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/news-bot",
                "X-Title": "News Bot"
            },
            timeout=30
        )
        if r.status_code == 200:
            data = r.json()
            result = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if result and len(result) > 5:
                result = result.strip('"\'`')
                log.info("   ✅ OpenRouter (Qwen 2.5 72B) succeeded")
                return result
        else:
            log.info(f"   ⏭️ OpenRouter failed: HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"OpenRouter err: {e}")
    return None


def _is_arabic_quality_good(text):
    """التحقق من جودة النص العربي
    يرفض النصوص التي تحتوي على كلمات إنجليزية كثيرة (مكسورة)
    Returns: True لو النص عربي جيد، False لو مكسور
    """
    if not text or len(text) < 5:
        return False
    # الكلمات العربية المتوقعة (الأحرف العربية)
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    # الكلمات الإنجليزية (تسلسلات حروف لاتينية 4+ حروف)
    english_words = re.findall(r'[a-zA-Z]{4,}', text)
    # القائمة المسموح بها - أسماء محددة فقط
    allowed_english = {
        # عملات
        "Bitcoin", "Ethereum", "Binance", "Coinbase", "USDT", "USDC", "Tether",
        "Solana", "Cardano", "Ripple", "Litecoin", "Dogecoin", "Polkadot",
        "Chainlink", "Avalanche", "Polygon", "Arbitrum", "Optimism", "Uniswap",
        "Aptos", "Sui", "Near", "Fantom", "Cosmos", "Tron", "Starknet",
        # شركات كريبتو
        "BlackRock", "MicroStrategy", "Grayscale", "Fidelity", "Kraken",
        "Bybit", "Huobi", "Gemini", "Bitfinex", "Anchorage", "Robinhood",
        "Van", "Eck", "Franklin", "Templeton",  # من Van Eck, Franklin Templeton
        # اختصارات
        "SEC", "ETF", "DeFi", "NFT", "Web3", "DAO", "MiCA", "FIT21",
        "API", "USD", "CFTC", "Lido",
        # شخصيات
        "Saylor", "Gensler", "Vitalik", "Satoshi", "Musk", "Buterin",
        "Armstrong", "Zhao", "Dorsey", "Hoskinson", "Fink", "Wood",
    }
    # فحص صارم: أي كلمة إنجليزية غير مسموح بها = مكسور
    suspicious_english = [w for w in english_words if w not in allowed_english]
    if len(suspicious_english) > 0:
        log.warning(f"   ⚠️ Translation has suspicious English: {suspicious_english[:5]}")
        return False
    # لو نسبة الأحرف العربية أقل من 25% → مكسور
    if len(text) > 20 and arabic_chars / len(text) < 0.25:
        log.warning(f"   ⚠️ Translation has low Arabic ratio: {arabic_chars/len(text)*100:.0f}%")
        return False
    # فحص علامات غريبة (شيفرة/أخطاء)
    weird_patterns = [r'\*.*\*', r'\.\.\."', r'" *\*', r'```', r'\.\.\. *Key']
    for pattern in weird_patterns:
        if re.search(pattern, text):
            log.warning(f"   ⚠️ Translation has weird pattern: {pattern}")
            return False
    return True


def _is_translation_complete(text):
    """فحص اكتمال الترجمة — يرفض النصوص المقطوعة
    يعيد True إذا كانت الترجمة مكتملة، False إذا كانت مقطوعة.
    """
    if not text:
        return False
    trimmed = text.strip()

    # علامات نهاية غير مكتملة (حروف جر وأدوات عربية + رموز)
    BAD_ENDINGS = (
        "على", "في", "من", "إلى", "عن", "مع",
        "بسبب", "بعد", "قبل", "حول", "حتى", "خلال",
        "بين", "ضد", "عبر", "نحو", "لدى",
        "وذلك على", "وذلك في", "وذلك من",
        "✉️", "...", "،", ":",
    )
    if trimmed.endswith(BAD_ENDINGS):
        log.info(f"   ⏭️ Translation incomplete — ends with: '{trimmed[-20:]}'")
        return False

    # نصوص طويلة (250+ حرف) بدون علامة نهاية جملة → غالباً مقطوعة
    if len(trimmed) >= 250 and not re.search(r'[.!؟?!]$', trimmed):
        log.info(f"   ⏭️ Translation incomplete — no ending punctuation (len={len(trimmed)})")
        return False

    return True


def _truncate_at_sentence(text, max_len=1200):
    """قص النص عند نهاية جملة بدلاً من قص عشوائي
    يبحث عن آخر علامة نهاية جملة قبل max_len ويقص عندها.
    لو لم يجد، يبحث عن آخر مسافة.
    """
    if len(text) <= max_len:
        return text
    chunk = text[:max_len]
    # البحث عن آخر نقطة/علامة نهاية جملة
    for punct in ('. ', '.\n', '! ', '? ', '। '):
        last = chunk.rfind(punct)
        if last > max_len * 0.5:  # لا نقص لأقل من النصف
            return chunk[:last + 1]
    # بديل: آخر مسافة قبل النهاية
    last_space = chunk.rfind(' ')
    if last_space > max_len * 0.5:
        return chunk[:last_space]
    return chunk


def translate_to_arabic(text, force=False):
    """ترجمة النص للعربية - نظام طبقتين:
    1️⃣ Gemini (ترجمة + صياغة صحفية)
    2️⃣ Google Translate (ترجمة حرفية مجانية — بديل موثوق)

    Gemini يُخرج (title, body) بفضل البرومبت.
    Google Translate يُرجع نصاً مسطحاً (title=النص, body="").
    """
    if not text or len(text) < 3:
        return text
    # قص النص الطويل عند نهاية جملة (ليس عند عدد أحرف ثابت)
    text = _truncate_at_sentence(text, max_len=1200)
    cache_key = hashlib.md5(text.encode()).hexdigest()[:12]
    if not force and cache_key in _translation_cache:
        return _translation_cache[cache_key]

    # استخراج الأسماء الحرجة من النص الأصلي مرة واحدة
    entities = _extract_entities(text)
    has_entities = len(entities) > 0
    if has_entities:
        log.info(f"   📋 Entities found: {entities}")

    # ═══ 1️⃣ الطبقة 1: Gemini (ترجمة + صياغة صحفية) ═══
    title_ar, body_ar = _translate_with_gemini(text)
    if title_ar:
        title_ar = _cleanup_translation(title_ar)
        body_ar = _cleanup_translation(body_ar) if body_ar else ""
        if title_ar and len(title_ar) > 3 and _is_arabic_quality_good(title_ar):
            if has_entities:
                check_text = title_ar + " " + body_ar
                ok, missing = _verify_entities(text, check_text)
                if not ok:
                    log.warning(f"   🔄 Gemini retry — missing: {missing}")
                    title_ar, body_ar = _translate_with_gemini(text, missing_names=missing)
                    if title_ar:
                        title_ar = _cleanup_translation(title_ar)
                        body_ar = _cleanup_translation(body_ar) if body_ar else ""
                        if title_ar and len(title_ar) > 3 and _is_arabic_quality_good(title_ar):
                            check2 = title_ar + " " + body_ar
                            ok2, missing2 = _verify_entities(text, check2)
                            if ok2:
                                # نحفظ العنوان (أو العنوان+الخبر معاً)
                                final = title_ar if not body_ar else title_ar + "\n" + body_ar
                                _translation_cache[cache_key] = final
                                return final
                            else:
                                log.warning(f"   ⚠️ Gemini retry still missing: {missing2} — accepting")
                                final = title_ar if not body_ar else title_ar + "\n" + body_ar
                                _translation_cache[cache_key] = final
                                return final
                        else:
                            log.info("   ⏭️ Gemini retry quality low")
                else:
                    final = title_ar if not body_ar else title_ar + "\n" + body_ar
                    _translation_cache[cache_key] = final
                    return final
            else:
                final = title_ar if not body_ar else title_ar + "\n" + body_ar
                _translation_cache[cache_key] = final
                return final
        else:
            log.info("   ⏭️ Gemini output quality too low")

    # ═══ 2️⃣ الطبقة 2: Google Translate (مجاني، بدون مفتاح) ═══
    log.info("   🔄 Falling back to Google Translate...")
    translated = _translate_with_google(text)
    if translated:
        translated = _cleanup_translation(translated)
        if translated and len(translated) > 3:
            # فحص مخفف لـ Google Translate — نقبل حتى لو كان فيه كلمات إنجليزية
            # المهم أن يكون فيه نص عربي واضح
            arabic_chars = sum(1 for c in translated if '\u0600' <= c <= '\u06FF')
            if len(translated) > 20 and arabic_chars / len(translated) < 0.15:
                log.info("   ⏭️ Google Translate output has almost no Arabic")
            else:
                log.info("   ✅ Google Translate accepted")
                _translation_cache[cache_key] = translated
                return translated

    # ❌ فشلت كل الطبقات
    log.warning("   ❌ All translation methods failed - skipping news")
    return None


def _cleanup_translation(text):
    """تنظيف شامل للنص المترجم من المخلفات والأخطاء الشائعة
    يزيل:
    - بقايا الـ placeholders (ar, ZZ, Uni, أرقام مفردة بين قوسين)
    - الكلمات الإنجليزية المعلقة التي تسربت
    - المسافات الزائدة
    - علامات الترقيم المكررة
    قائمة موسعة جداً من الكلمات المتسربة المعروفة
    """
    if not text:
        return text

    result = text

    # 1️⃣ إزالة بقايا الـ placeholders
    result = re.sub(r"«\s*ZZ\s*\d+\s*ZZ\s*»", "", result)
    result = re.sub(r"ZZ\s*\d+\s*ZZ", "", result)
    result = re.sub(r"\[\[\s*\d+\s*\]\]", "", result)
    result = re.sub(r"\[\s*\d+\s*\]", "", result)
    result = re.sub(r"\(\s*\d+\s*\)", "", result)

    # 2️⃣ قائمة موسعة جداً من الكلمات الإنجليزية المتسربة المعروفة
    # هذه كلمات تظهر بسبب أخطاء الترجمة الآلية
    suspicious_words = [
        # رموز لغات (من NLLB/Google)
        "uni", "zzz", "zz", "xx", "yy", "arb", "latn", "arab", "eng",
        "eng_latn", "ar", "en", "fr", "de", "es", "zh", "ja", "ko", "ru",
        # رموز تقنية متسربة (ليست أسماء عملات)
        "rss", "xml", "html", "json", "http", "https", "url", "api",
        # كلمات meta
        "content", "title", "description", "summary", "image", "thumbnail",
        # كلمات قصيرة متسربة
        "tar", "raw", "src", "alt", "tag", "div", "span", "class",
    ]
    for word in suspicious_words:
        # فقط لو ظهرت ككلمة منفصلة (3 حروف أو أقل)
        if len(word) <= 4:
            result = re.sub(r"\b" + word + r"\b", "", result, flags=re.IGNORECASE)

    # 2.5️⃣ إزالة الكلمات الإنجليزية القصيرة المعلقة (1-4 حروف)
    # التي تظهر بين نص عربي (placeholder leaks من NLLB)
    # نمط: نص عربي + مسافة + كلمة إنجليزية قصيرة + مسافة + نص عربي
    result = re.sub(
        r"([\u0600-\u06FF])\s+[a-zA-Z]{1,4}\s+([\u0600-\u06FF])",
        r"\1 \2",
        result
    )
    # نمط: بداية النص + كلمة إنجليزية قصيرة + مسافة + نص عربي
    result = re.sub(
        r"^[a-zA-Z]{1,4}\s+([\u0600-\u06FF])",
        r"\1",
        result
    )
    # نمط: نص عربي + مسافة + كلمة إنجليزية قصيرة في النهاية
    result = re.sub(
        r"([\u0600-\u06FF])\s+[a-zA-Z]{1,4}$",
        r"\1",
        result
    )

    # 3️⃣ إزالة الأقواس الفارغة والعلامات الفارغة
    result = re.sub(r"\(\s*\)", "", result)
    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"«\s*»", "", result)
    result = re.sub(r"\{\s*\}", "", result)
    result = re.sub(r"'\s*'", "", result)
    result = re.sub(r'"\s*"', "", result)
    result = re.sub(r"''", "", result)
    result = re.sub(r'""', "", result)

    # 4️⃣ إزالة المسافات الزائدة
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\s+\.", ".", result)
    result = re.sub(r"\s+,", ",", result)
    result = re.sub(r"\.\s*\.\s*\.", ".", result)
    result = re.sub(r"\.\s*\.\s*", ". ", result)
    result = re.sub(r"\s*,\s*", "، ", result)
    result = re.sub(r"\s+،", "،", result)

    # 5️⃣ إزالة علامات الاقتباس الفردية الغريبة
    result = re.sub(r"''+", "", result)
    result = re.sub(r"'(?:\s*'')+", "", result)

    # 6️⃣ تنظيف البداية والنهاية
    result = result.strip()
    result = result.strip(" .,،:؛")
    result = result.strip()

    # 7️⃣ إزالة الكلمات المكررة المتجاورة
    result = re.sub(r"\b(\w+)\s+\1\b", r"\1", result)

    # 8️⃣ إزالة الكلمات الإنجليزية المعلقة المتبقية
    # (التي لا معنى لها في سياق عربي)
    # نمط: كلمة إنجليزية (1-4 حروف) محاطة بعلامات ترقيم عربية
    result = re.sub(
        r"([\u0600-\u06FF،؛.])\s+[a-zA-Z]{1,4}\s*([\u0600-\u06FF،؛.])",
        r"\1 \2",
        result
    )

    # 9️⃣ تنظيف نهائي للمسافات
    result = re.sub(r"\s+", " ", result)
    result = result.strip()

    return result


def translate_news_item(item):
    """ترجمة عنوان وملخص الخبر للعربية"""
    title = item.get("title", "")
    summary = item.get("summary", "")
    item["title_ar"] = translate_to_arabic(title)
    if summary:
        item["summary_ar"] = translate_to_arabic(summary)
    else:
        item["summary_ar"] = ""
    return item


def translate_source_name(source):
    """ترجمة أسماء المصادر للعربية
    إضافة المصادر الجديدة الموثوقة
    """
    sources_ar = {
        "CoinDesk": "كوين ديسك",
        "Cointelegraph": "كوين تيليغراف",
        "Decrypt": "ديكريبٽ",
        "Bitcoin.com": "بيتكوين دوت كوم",
        "Crypto.News": "كريبتو نيوز",
        "NewsBTC": "نيوز بي تي سي",
        "BeInCrypto": "بي إن كريبتو",
        "Google News AR - Bitcoin": "أخبار بيتكوين",
    }
    return sources_ar.get(source, source)


def translate_coin_name(symbol):
    """ترجمة أسماء العملات للعربية"""
    coins_ar = {
        "BTC": "بيتكوين",
        "ETH": "إيثيريوم",
        "SOL": "سولانا",
        "XRP": "ريبل",
        "ADA": "كاردانو",
        "DOGE": "دوجكوين",
        "AVAX": "أفالانش",
        "MATIC": "بوليغون",
        "LINK": "تشين لينك",
        "DOT": "بولكادوت",
        "LTC": "لايتكوين",
        "BNB": "بينانس كوين",
        "USDT": "تيثر",
        "APT": "أبتوس",
        "ARB": "أربيترم",
        "OP": "أوبتيميزم",
        "SUI": "سوي",
        "SEI": "سي",
        "TON": "تونكوين",
    }
    return f"{symbol} ({coins_ar.get(symbol, symbol)})"