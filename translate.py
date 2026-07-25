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
# 🛡️ حماية أسماء الكيانات من الترجمة — قاموس شامل
# ═══════════════════════════════════════════════════════════
CRITICAL_NAMES = [
    # ── العملات الرئيسية ──
    "bitcoin", "btc", "ethereum", "eth", "ether", "solana", "sol", "xrp", "ripple",
    "cardano", "ada", "dogecoin", "doge", "avalanche", "avax", "polkadot", "dot",
    "chainlink", "link", "polygon", "matic", "litecoin", "ltc", "tron", "trx",
    "arbitrum", "arb", "optimism", "op", "aptos", "apt", "sui", "sei", "near",
    "uniswap", "aave", "fantom", "ftm", "cosmos", "atom", "stellar", "xlm",
    "hedera", "hbar", "shiba", "shib", "pepe", "toncoin", "ton", "near protocol",
    "binance coin", "bnb", "usdt", "usdc", "tether", "dai",
    "bitcoin cash", "bch", "ethereum classic", "etc", "eos", "eos",
    "monero", "xmr", "tezos", "xtz", "vechain", "vet", "theta", "theta",
    "filecoin", "fil", "neo", "iota", "miota", "zcash", "zec", "dash", "dash",
    "waves", "waves", "icon", "icx", "qtum", "qtum", "omisego", "omg",
    "lisk", "lsk", "nano", "nano", "aelf", "elf", "zilliqa", "zil",
    "decred", "dcr", "siacoin", "sc", "steem", "steem", "bitshares", "bts",
    "decentraland", "mana", "sandbox", "sand", "axie infinity", "axs",
    "render", "rndr", "fetch.ai", "fet", "internet computer", "icp",
    "kava", "kava", "thorchain", "rune", "ocean", "ocean",
    "injective", "inj", "celestia", "tia", "kaspa", "kas",
    "worldcoin", "wld", "starknet", "strk", "zk sync", "zks",
    "linea", "linea", "mantle", "mnt", "scroll", "scroll",
    "base", "base", "blast", "blast", "mode", "mode",
    "polygon cd", "matic", "celestia", "tia", "kaspa", "kas",
    "manta", "manta", "bonk", "bonk", "wif", "wif",
    "jupiter", "jup", "wormhole", "w", "eigenlayer", "eigen",
    "pengu", "pengu", "floki", "floki", "bome", "bome",
    "jambo", "jambo", "berachain", "bera", "megaeth", "mega",
    "sonic", "sonic", "virtuals", "virtual", "ai16z", "ai16z",
    "lightchain", "light", "dawn protocol", "dawn",

    # ── عملات إضافية ──
    "maker", "mkr", "lido dao", "ldo", "rocket pool", "rpl",
    "curve", "crv", "synthetix", "snx", "compound", "comp",
    "yearn", "yfi", "balancer", "bal", "sushi", "sushi",
    "pancake", "cake", "1inch", "1inch", "kyber", "knc",
    "loopring", "lrc", "ren", "ren", "uma", "uma",
    "mstable", "mstable", "reflexer", "raai", "bakkt", "bakkt",
    "gmx", "gmx", "dydx", "dydx", "perp", "perp",
    "gns", "gns", "velodrome", "velo", "aerodrome", "aero",
    "camelot", "camelot", "trader joe", "joe", "raydium", "ray",
    "orca", "orca", "meteora", "meteora", "jupiter", "jup",
    "drift", "drift", "hyperliquid", "hype", "winr", "winr",
    "ethena", "ethena", "pendle", "pendle", "echo", "echo",
    "parcl", "prcl", "io net", "io", "akash", "akt",
    "grass", "grass", "aethir", "ath", "decentralized gpu", "gpu",
    "ondo", "ondo", "mantra", "om", "polymath", "polymath",
    "centrifuge", "cfg", "maple", "mpl", "goldfinch", "gfi",
    "truefi", "truf", "clearpool", "cpool", "credix", "credix",
    "arbitrum", "arb", "base", "base", "mantle", "mnt",
    "scroll", "scroll", "zircuit", "zircuit", "morpho", "morpho",
    "eigenlayer", "eigen", "symbiotic", "symbiotic",
    "karak", "karak", "etherfi", "ethfi", "renzo", "renzo",
    "puffer", "puffer", "swell", "swell", "stakewise", "stakewise",
    "bedrock", "bedrock", "binance", "bnb", "staked", "staked",
    "jito", "jito", "marinade", "marinade", "sanctum", "sanctum",
    "fragment", "fragment", "blastr", "blastr", "bond", "bond",
    "solayer", "solayer", "shnap", "shnap", "dackie", "dackie",
    "solv", "solv", "berkshire", "berkshire",

    # ── بروتوكولات DeFi ──
    "makerdao", "maker dao", "compound finance", "aave protocol",
    "curve finance", "synthetix protocol", "yearn finance",
    "balancer protocol", "convex", "convex finance",
    "tokemak", "tokemak", "bancor", "bancor",
    "the graph", "grt", "livepeer", "lpt",
    "ens", "ens domain", "arweave", "ar",
    "numeraire", "nmr", "melon", "melon",
    "radix", "xrd", "aleph zero", "azero",
    "neon", "neon", "zeta", "zeta",
    "kinto", "kinto", "lumia", "lumia",
    "morpheus", "morpheus", "ai", "ai agent",

    # ── عملات الستيبل كوين ──
    "tether", "usdt", "usdc", "circle", "paxos", "trust token", "trueusd", "tusd",
    "gemini dollar", "gusd", "dai", "frax", "lusd", "crvusd",
    "pyusd", "pyusd", "paypal usd", "fdusd", "first digital usd",
    "euri", "euri", "usdp", "usdp",

    # ── منصات التداول المركزية CEX ──
    "binance", "coinbase", "kraken", "bybit", "okx", "kucoin",
    "bitfinex", "bitstamp", "gemini", "crypto.com", "huobi", "htx",
    "gate.io", "mexc", "bitget", "upbit", "bithumb",
    "deribit", "bitmex", "phemex", "bingx",
    "poloniex", "kucoin", "ascendex",
    "htx", "kucoin", "bitforex",
    "cryptocom", "crypto.com",

    # ── منصات التداول اللامركزية DEX ──
    "uniswap", "sushiswap", "pancakeswap", "curve", "balancer",
    "raydium", "orca", "meteora", "jupiter exchange",
    "1inch", "paraswap", "0x protocol",
    "trader joe", "spirit", "spookyswap",
    "camelot", "zyberswap", "thena",
    "ramsese", "ramses", "velodrome", "aerodrome",
    "astroport", "astro", "whiteSwap", "odos",
    "hashflow", "hashflow", "kyberswap", "woofi",
    "maverick", "maverick", "clipper", "clipper",
    "drift", "hyperliquid", "dex",

    # ── منصات الستاكينغ والرستاكينغ ──
    "lido", "rocket pool", "stakewise", "frax",
    "eigenlayer", "symbiotic", "karak",
    "etherfi", "renzo", "puffer", "swell",
    "bedrock", "diva", "stadera",
    "jito", "marinade", "sanctum",
    "restaking", "liquid staking",
    "lsd", "lrt", "lst",

    # ── بروتوكولات L1 و L2 ──
    "ethereum", "solana", "bitcoin", "avalanche", "polkadot",
    "cosmos", "cardano", "near protocol", "aptos", "sui",
    "algorand", "algo", "tezos", "xtz",
    "fantom", "celo", "flow", "flow",
    "hedera", "internet computer", "icp",
    "kaspa", "kas", "monero", "xmr",
    "arbitrum", "optimism", "base",
    "polygon", "scroll", "linea", "mantle",
    "zk sync", "starknet", "zircuit", "manta",
    "metis", "metis", "bob", "bob network",
    "mode network", "blast network",
    "berachain", "sonic", "megaeth",

    # ── جسور بين السلاسل ──
    "wormhole", "layerzero", "stargate", "across",
    "hop protocol", "synapse", "celer",
    "allbridge", "multichain", "axelar",
    "renbridge", "nomad", "debridge",
    "relay chain", "ibc",

    # ── أوراكل ──
    "chainlink", "pyth network", "pyth",
    "band protocol", "dia", "uma oracle",
    "supra", "supra", "chronicle", "chronicle",
    "redstone", "redstone",

    # ── منصات NFT ──
    "opensea", "magic eden", "blur", "rarible",
    "foundation", "zora", "sudoswap", "looks rare",
    "yawww", "tensor", "trove",
    "magic eden", "okx nft",

    # ── شركات ومؤسسات كريبتو ──
    "binance", "coinbase", "ripple labs", "circle",
    "tether limited", "blockstream", "digital currency group",
    "consensys", "paradigm", "a16z", "andreessen horowitz",
    "sequoia", "paradigm", "polychain", "jump crypto",
    "alameda research", "ftx",
    "microstrategy", "strategy", "square", "block",
    "paypal", "visa", "mastercard",
    "silvergate", "signature bank",
    "galaxy digital", "coinshares", "21shares",
    "grayscale investments", "proshares",
    "bitwise", "vaneck", "wisdomtree", "invesco",
    "hashdex", "paxos",

    # ── صناديق ETF ──
    "ibit", "fbtc", "gbtc", "etha", "ezet",
    "bitb", "bitx", "hodi", "hodl",
    "brrr", "cibc", "defi", "btcd",
    "solo", "asic", "bugg", "btf",
    "abtc", "tbtc", "btcw", "cbtc",
    "arkb", "btco", "bitq", "bkch",
    "satoshi", "wisdomtree", "van eck",
    "spot bitcoin", "spot etf",
    "bitcoin etf", "ethereum etf", "crypto etf",
    "spot ether", "solana etf",

    # ── جهات تنظيمية ──
    "sec", "securities and exchange commission", "cftc",
    "commodity futures trading commission",
    "fincen", "european central bank", "ecb",
    "fca", "mas", "sfc", "asic",
    "gensler", "gary gensler", "chair gensler",
    "powell", "jerome powell",
    "baum", "peirce", "crypto mom",
    "eu parliament", "mica", "markets in crypto assets",
    "basel committee", "fatf",
    "federal reserve", "fed", "fomc",
    "treasury", "yellen", "janet yellen",
    "macron", "lagarde",

    # ── أشخاص بارزون ──
    "satoshi nakamoto", "satoshi", "vitalik buterin", "vitalik",
    "changpeng zhao", "cz", "cz binance",
    "brian armstrong", "brad garlinghouse",
    "michael saylor", "saylor",
    "elon musk", "musk",
    "jack dorsey", "dorsey",
    "sam bankman-fried", "sbf", "bankman fried",
    "do kwon", "su zhu", "kyle davies",
    "hayden adams", "stani kulechov",
    "adam back", "hal finney",
    "nick szabo", "gavin wood",
    "charles hoskinson", "dan larimer",
    "jihan wu", "micree zhan",
    "roger ver", "barry silbert",
    "cameron winklevoss", "tyler winklevoss",
    "anthony pompliano", "pomp",
    "raoul pal", "planb",
    "whale", "whales",
    "vitalik", "buterin",

    # ── محافظ وأدوات ──
    "metamask", "trust wallet", "phantom",
    "ledger", "trezor", "exodus",
    "rabby", "rabby wallet", "okx wallet",
    "keplr", "keplr wallet", "cosmostation",
    "phantom wallet", "solflare", "backpack",
    "coinbase wallet", "bitget wallet",
    "safe", "safe wallet", "gnosis safe",
    "rainbow", "rainbow wallet",
    "hardware wallet", "cold wallet", "hot wallet",

    # ── مستكشفات وتحليلات ──
    "etherscan", "bscscan", "solscan",
    "polygonscan", "arbiscan", "snowtrace",
    "blockchain.com", "mempool.space",
    "dexscreener", "dextools", "coingecko", "coinmarketcap",
    "tradingview", "glassnode", "intotheblock",
    "nansen", "dune analytics", "dune",
    "token terminal", "defi llama",
    "l2beat", "l2beat", "debank",
    "arkham", "arkham intelligence",
    "whale alert", "lookonchain", "scam sniffer",
    "bubblemaps", "monitordesk",
    "coinbase international", "coinbase advanced",

    # ── تعدين ──
    "bitmain", "antminer", "microbt", "whatsminer",
    "canaan", "avalonminer", "foundry usa",
    "marathon digital", "riot platforms",
    "core scientific", "hive blockchain",
    "clean spark", "bitfarms",
    "terawulf", "iris energy",
    "poolin", "f2pool", "antpool",
    "btc.com", "viabtc", "slush pool",
    "hash rate", "hasrate", "difficulty adjustment",
    "asic", "asic miner",

    # ── DePIN ──
    "render network", "helium", "hnt",
    "filecoin", "arweave",
    "akash network", "io.net", "ionet",
    "grass network", "aethir", "decentralized gpu",
    "peaq", "peaq network",
    "xai", "xai network",

    # ── عملات AI ──
    "fetch.ai", "fet", "ocean protocol",
    "singularitynet", "agi", "agix",
    "render token", "rndr", "worldcoin", "wld",
    "bittensor", "tao", "akash", "akt",
    "graph token", "grt", "livepeer", "lpt",
    "ritual", "ritual", "virtuals protocol",
    "ai16z", "ai16z", "arc", "arc",
    "game", "game",

    # ── RWA ──
    "ondo finance", "ondo", "mantra finance", "mantra",
    "polymath", "centrifuge",
    "maple finance", "goldfinch",
    "truefi", "clearpool", "credix",
    "tangible", "tangible",

    # ── عملات الميم ──
    "dogecoin", "doge", "shiba inu", "shib",
    "pepe", "floki", "bonk", "wif",
    "bome", "pengu", "mog",
    "brett", "based", "toshi",
    "neiro", "neiro", "first neiro",
    "michi", "spooky",
    "popcat", "popcat", "mew",
    "cheems", "cheems",

    # ── إعلام كريبتو ──
    "coindesk", "cointelegraph", "decrypt",
    "beincrypto", "crypto.news", "coinpedia",
    "blockworks", "bitcoinist",
    "the block", "block", "forkast",
    "decrypt media",

    # ── مصطلحات عامة ──
    "defi", "nft", "nfts", "web3", "dao", "daos",
    "etf", "etfs", "ipo", "ico", "ieo", "ido",
    "dex", "cex", "cefi",
    "hodl", "fomo", "fud", "dyor", "ngu",
    "rekt", "wagmi", "lambo", "gm",
    "altcoin", "altcoins", "stablecoin", "stablecoins",
    "meme coin", "meme coins", "memecoin",
    "shitcoin", "shitcoins",
    "token", "tokens", "coin", "coins",
    "blockchain", "blockchains", "crypto",
    "cryptocurrency", "cryptocurrencies",
    "mining", "miner", "miners",
    "staking", "validator", "validators",
    "consensus", "node", "nodes",
    "block", "blocks", "genesis block",
    "hash", "hashrate", "nonce",
    "private key", "public key", "seed phrase",
    "gas fee", "gas fees", "transaction fee",
    "smart contract", "smart contracts",
    "erc-20", "erc-721", "erc-1155",
    "bep-20", "bep-2", "spl",
    "wrapped", "wrapped bitcoin", "wbtc",
    "wrapped ether", "weth",
    "liquid staked", "steth", "reth",
    "perpetual", "perpetuals", "perps",
    "options", "futures", "swap", "swaps",
    "amm", "automated market maker",
    "order book", "limit order", "market order",
    "yield", "apy", "apr",
    "tvl", "total value locked",
    "liquidity", "liquidity pool",
    "impermanent loss",
    "slippage", "spread",
    "market cap", "market capitalization",
    "circulating supply", "total supply",
    "dilution", "fully diluted",
    "ath", "atl", "all-time high", "all-time low",
    "support", "resistance",
    "volume", "24h volume", "trading volume",
    "candlestick", "candle", "timeframe",
    "bullish", "bearish", "bull", "bear",
    "pump", "dump", "pump and dump",
    "whale", "whales", "retail",
    "institutional", "institutions",
    "satoshi", "satoshis",
    "fiat", "off-chain", "on-chain",
    "mainnet", "testnet", "devnet",
    "hard fork", "soft fork", "fork",
    "upgrade", "roadmap",
    "airdrop", "airdrops",
    "token burn", "token unlock", "vesting",
    "whitelist", "allowlist",
    "presale", "public sale", "token generation event",
    "launch", "launchpad",
    "governance", "proposal", "voting",
    "treasury", "protocol",
    "ecosystem", "network",
    "hack", "hacked", "exploit", "vulnerability",
    "audit", "auditor",
    "phishing", "scam", "rug pull",
    "sanction", "sanctioned", "blacklist",
    "compliance", "aml", "kyc",
    "regulation", "regulated", "regulatory",
    "banned", "banned crypto",
    "legal tender", "central bank digital currency", "cbdc",
    "inflows", "outflows",
    "deposits", "withdrawals",
    "hot wallet", "cold storage",
    "multi-sig", "multisig",
    "zero-knowledge", "zk", "zkproof",
    "optimistic rollup", "zkevm",
    "rollup", "rollups",
    "sharding", "data availability",
    "modular blockchain", "modular",
    "celestia", "data availability layer",
    "sequencer", "proposer",
    "relayer", "prover",
    " mev", "maximal extractable value",
    "flash loan", "flash loans",
    "oracle", "oracles",
    "bridges", "bridge",
    "nft marketplace", "nft collection",
    "pfp", "profile picture",
    "floor price", "minting",
    "mint", "minted",
    "ens", "domain name",
    "metaverse",
    "play-to-earn", "p2e", "gamefi",
    "socialfi", "depin", "depin",
    "rebase", "rebas",
    "liquidation", "liquidated",
    "margin", "margin trading",
    "leverage", "leveraged",
    "long", "short", "position",
    "take profit", "stop loss",
    "tp", "sl",
    "buy", "sell", "hold",
    "accumulation", "distribution",
    "breakout", "breakdown",
    "consolidation", "trend",
    "resistance level", "support level",
    "fibonacci", "moving average", "rsi",
    "macd", "bollinger",
    "candlestick pattern", "chart pattern",
    "technical analysis", "fundamental analysis",
    "inflation", "deflation", "hyperinflation",
    "quantitative easing", "qe",
    "interest rate", "rate cut", "rate hike",
    "fomc", "federal reserve", "fed",
    "gdp", "cpi", "ppi", "unemployment",
    "recession", "soft landing",
    "monetary policy", "fiscal policy",
    "s&p 500", "nasdaq", "dow jones",
    "treasury bond", "treasury yield",
    "us dollar", "dollar index", "dxy",
    "gold price", "oil price",
    "correlation", "decoupling",
    "flight to safety", "risk-on", "risk-off",
    "halving", "bitcoin halving",
    "difficulty", "block reward",
    "confirmation", "unconfirmed transaction",
    "mempool", "pending transaction",
    "finality", "confirmation time",
    "throughput", "tps", "transactions per second",
    "latency", "scalability",
    "interoperability", "composability",
    "sovereign", "appchain",
    "sidechain", "parachain",
    "cancellation", "pause", "unpause",
    "emergency", "circuit breaker",
    "depeg", "depegged",
    "solana ecosystem", "ethereum ecosystem",
    "bitcoin network", "solana network",
]

GLOSSARY_AR = {
    # ── مصطلحات التداول والسوق ──
    "smart wallet": "المحفظة الذكية",
    "smart contract": "العقد الذكي",
    "smart contracts": "العقود الذكية",
    "multi-chain": "متعدد السلاسل",
    "cross-chain": "عبر السلاسل",
    "layer 2": "الطبقة الثانية",
    "layer 1": "الطبقة الأولى",
    "bull market": "السوق الصاعد",
    "bear market": "السوق الهابط",
    "bull run": "صعود قوي",
    "all-time high": "أعلى مستوى تاريخي",
    "all-time low": "أدنى مستوى تاريخي",
    "market cap": "القيمة السوقية",
    "market capitalization": "القيمة السوقية",
    "open interest": "المركزيات المفتوحة",
    "funding rate": "سعر التمويل",
    "liquidation": "تصفية",
    "liquidated": "تمت تصفيته",
    "leverage": "الرافعة المالية",
    "futures": "العقود الآجلة",
    "perpetual": "العقود الدائمة",
    "options": "الخيارات",
    "margin trading": "التداول بالهامش",
    "flash crash": "انهيار مفاجئ",
    "correction": "تصحيح",
    "rally": "ارتفاع",
    "surge": "قفزة",
    "plunge": "انهيار حاد",
    "crash": "انهيار",
    "dip": "هبوط",
    "recovery": "تعافي",
    "bounce": "ارتداد",
    "breakout": "اختراق",
    "breakdown": "كسر دعم",
    "consolidation": "تماسك",
    "accumulation": "تراكم",
    "distribution": "توزيع",
    "pump": "قفزة",
    "dump": "انهيار",
    "whale": "حوت",
    "retail": "المستثمر الأفرادي",
    "institutional": "مؤسسي",
    "volume": "حجم التداول",
    "trading volume": "حجم التداول",
    "24h volume": "حجم 24 ساعة",
    "support": "دعم",
    "resistance": "مقاومة",
    "support level": "مستوى دعم",
    "resistance level": "مستوى مقاومة",
    "trend": "اتجاه",
    "bullish": "صاعدي",
    "bearish": "هابط",
    "candlestick": "شمعة",
    "candlestick pattern": "نمط الشموع",
    "chart pattern": "نمط بياني",
    "technical analysis": "التحليل الفني",
    "fundamental analysis": "التحليل الأساسي",
    "take profit": "جني الأرباح",
    "stop loss": "وقف الخسارة",
    "long": "شراء",
    "short": "بيع",
    "position": "مركز",
    "order book": "دفتر الأوامر",
    "limit order": "أمر محدد",
    "market order": "أمر سوقي",
    "slippage": "انزلاق",
    "spread": "الفرق",
    "fibonacci": "فيبوناتشي",
    "moving average": "المتوسط المتحرك",
    "rsi": "مؤشر القوة النسبية",
    "macd": "ماكد",
    "bollinger": "بولينجر",
    "risk-on": "تقبل المخاطر",
    "risk-off": "تجنب المخاطر",
    "flight to safety": "لجوء للملاذ الآمن",

    # ── مصطلحات الستاكينغ والتعدين ──
    "staking": "التحصيص",
    "restaking": "إعادة التحصيص",
    "liquid staking": "التحصيص السائل",
    "mining": "التعدين",
    "miner": "المعدّن",
    "miners": "المعدّنين",
    "mining pool": "تجمع التعدين",
    "halving": "التنصيف",
    "bitcoin halving": "تنصيف بيتكوين",
    "hash rate": "معدل الهاش",
    "hashrate": "معدل الهاش",
    "difficulty": "الصعوبة",
    "difficulty adjustment": "تعديل الصعوبة",
    "block reward": "مكافأة الكتلة",
    "proof of stake": "إثبات الحصة",
    "proof of work": "إثبات العمل",
    "validator": "المُتحقق",
    "validators": "المُتحققين",
    "consensus": "إجماع",
    "confirmation": "تأكيد",
    "finality": "نهائية",
    "throughput": "سرعة معالجة",
    "tps": "معاملة بالثانية",
    "confirmation time": "وقت التأكيد",

    # ── مصطلحات DeFi ──
    "yield": "عائد",
    "apy": "العائد السنوي",
    "apr": "معدل العائد السنوي",
    "tvl": "إجمالي القيمة المقفلة",
    "total value locked": "إجمالي القيمة المقفلة",
    "liquidity": "سيولة",
    "liquidity pool": "مجمع السيولة",
    "impermanent loss": "خسارة غير دائمة",
    "amm": "صانع السوق الآلي",
    "automated market maker": "صانع السوق الآلي",
    "flash loan": "قرض فوري",
    "flash loans": "قروض فورية",
    "yield farming": "زراعة العائد",
    "lending protocol": "بروتوكول الإقراض",
    "borrowing": "اقتراض",
    "lending": "إقراض",
    "collateral": "ضمان",
    "over-collateralized": "مضمن بزيادة",
    "under-collateralized": "مضمن بنقص",
    "governance": "حوكمة",
    "proposal": "مقترح",
    "treasury": "الخزينة",
    "protocol": "البروتوكول",
    "decentralized": "لامركزي",
    "decentralized exchange": "منصة لامركزية",
    "dex": "منصة لامركزية",
    "cex": "منصة مركزية",

    # ── مصطلحات الأمان ──
    "hack": "اختراق",
    "hacked": "تم اختراقه",
    "hackers": "المخترقون",
    "exploit": "ثغرة أمنية",
    "exploited": "تم استغلاله",
    "vulnerability": "ثغرة",
    "stolen": "مُسروق",
    "stolen funds": "أموال مسروقة",
    "rug pull": "احتيال",
    "phishing": "تصيد",
    "scam": "احتيال",
    "auditor": "مدقق",
    "audit": "تدقيق",
    "sanction": "عقوبة",
    "sanctioned": "مُعاقَب",
    "blacklist": "قائمة سوداء",
    "compliance": "امتثال",
    "kyc": "اعرف عميلك",
    "aml": "مكافحة غسل الأموال",
    "white hack": "اختراق أخلاقي",
    "bug bounty": "مكافأة الثغرات",
    "malware": "برمجيات خبيثة",
    "ransomware": "فدية",
    "multi-sig": "توقيع متعدد",
    "multisig": "توقيع متعدد",
    "cold storage": "تخزين بارد",
    "cold wallet": "محفظة باردة",
    "hot wallet": "محفظة ساخنة",
    "hardware wallet": "محفظة matériel",

    # ── مصطلحات التوكنات ──
    "token": "توكن",
    "tokens": "توكنات",
    "token burn": "حرق توكن",
    "token unlock": "فك حجز توكن",
    "token generation event": "حدث إنشاء التوكن",
    "vesting": "جدولة الإطلاق",
    "vesting period": "فترة الجدولة",
    "airdrop": "إيردروب",
    "airdrops": "إيردروبات",
    "minting": "سك",
    "mint": "سك",
    "minted": "تم سكه",
    "presale": "بيع مسبق",
    "public sale": "بيع عام",
    "launchpad": "منصة إطلاق",
    "launch": "إطلاق",
    "upgrade": "تحديث",
    "depeg": "انفصال عن الدولار",
    "depegged": "انفصل عن الدولار",
    "rebase": "إعادة ضبط",
    "wrapped": "مغلف",
    "wrapped bitcoin": "بيتكوين مغلف",
    "wrapped ether": "إيثير مغلف",

    # ── مصطلحات البلوكتشين ──
    "blockchain": "سلسلة الكتل",
    "blockchains": "سلاسل الكتل",
    "crypto": "كريبتو",
    "cryptocurrency": "عملة رقمية",
    "stable": "عملة مستقرة",
    "stablecoin": "عملة مستقرة",
    "stablecoins": "عملات مستقرة",
    "block": "كتلة",
    "blocks": "كتل",
    "blockchain network": "شبكة البلوكتشين",
    "genesis block": "كتلة التكوين",
    "node": "عقدة",
    "nodes": "عقد",
    "hash": "هاش",
    "nonce": "رقم عشوائي",
    "private key": "مفتاح خاص",
    "public key": "مفتاح عام",
    "seed phrase": "عبارة البذرة",
    "gas fee": "رسوم الغاز",
    "gas fees": "رسوم الغاز",
    "gas": "رسوم الغاز",
    "transaction fee": "رسوم المعاملة",
    "mainnet": "الشبكة الرئيسية",
    "testnet": "شبكة الاختبار",
    "devnet": "شبكة التطوير",
    "hard fork": "انقسام صلب",
    "soft fork": "انقسام ناعم",
    "fork": "انقسام",
    "the merge": "الدمج",
    "sharding": "التجزئة",
    "data availability": "توفر البيانات",
    "modular": "معياري",
    "modular blockchain": "بلوكتشين معياري",
    "rollup": "رول أب",
    "rollups": "رول أب",
    "zkevm": "ماكينة إيثيوم خالية المعرفة",
    "zero-knowledge": "خالية المعرفة",
    "zk": "خالية المعرفة",
    "zkproof": "إثبات خالي من المعرفة",
    "optimistic rollup": "رول أب تفاؤلي",
    "sequencer": "المُرتب",
    "proposer": "المُقترح",
    "prover": "المُثبت",
    "relayer": "الناقل",
    "mev": "القيمة القصوى القابلة للاستخراج",
    "mempool": "ميمبول",
    "pending transaction": "معاملة معلقة",
    "unconfirmed transaction": "معاملة غير مؤكدة",
    "scalability": "قابلية التوسع",
    "interoperability": "التشغيل البيني",
    "composability": "القابلية التركيبية",
    "sidechain": "سلسلة جانبية",
    "parachain": "سلسلة متوازية",
    "appchain": "سلسلة التطبيقات",
    "sovereign": "ذاتي السيادة",
    "finality": "النهائية",
    "confirmation": "تأكيد",
    "ecosystem": "النظام البيئي",
    "network": "الشبكة",

    # ── مصطلحات NFT ──
    "nft": "NFT",
    "nfts": "NFTs",
    "nft marketplace": "سوق NFT",
    "nft collection": "مجموعة NFT",
    "floor price": "سعر الأرضية",
    "minting": "السك",
    "pfp": "صورة الملف الشخصي",
    "profile picture": "صورة الملف الشخصي",
    "metaverse": "العالم الافتراضي",

    # ── مصطلحات تنظيمية ──
    "spot etf": "صندوق ETF الفوري",
    "spot bitcoin": "بيتكوين الفوري",
    "bitcoin etf": "صندوق بيتكوين",
    "ethereum etf": "صندوق إيثيريوم",
    "crypto etf": "صندوق كريبتو",
    "spot ether": "إيثيريوم الفوري",
    "solana etf": "صندوق سولانا",
    "regulation": "تنظيم",
    "regulated": "مُنظَّم",
    "regulatory": "تنظيمي",
    "legal tender": "عملة قانونية",
    "cbdc": "عملة رقمية للبنك المركزي",
    "central bank digital currency": "عملة رقمية للبنك المركزي",
    "sec approval": "موافقة الهيئة",
    "sec rejected": "رفض الهيئة",
    "regulated exchange": "منصة مُنظَّمة",

    # ── مصطلحات اقتصادية كلّية ──
    "federal reserve": "الاحتياطي الفيدرالي",
    "interest rate": "سعر الفائدة",
    "rate cut": "خفض الفائدة",
    "rate hike": "رفع الفائدة",
    "fomc": "لجنة السوق الفيدرالية",
    "inflation": "التضخم",
    "deflation": "الانكماش",
    "quantitative easing": "التسهيل الكمي",
    "monetary policy": "السياسة النقدية",
    "fiscal policy": "السياسة المالية",
    "treasury bond": "سندات الخزانة",
    "treasury yield": "عائد الخزانة",
    "recession": "ركود",
    "soft landing": "هبوط ناعم",
    "gdp": "الناتج المحلي",
    "cpi": "مؤشر أسعار المستهلك",
    "dollar index": "مؤشر الدولار",
    "us dollar": "الدولار الأمريكي",
    "gold price": "سعر الذهب",
    "correlation": "ارتباط",
    "decoupling": "انفصال",
    "safe haven": "ملاذ آمن",
    "risk asset": "أصل مخاطر",

    # ── مصطلحات الجسور والترجيح ──
    "bridge": "جسر",
    "bridges": "جسور",
    "cross-chain bridge": "جسر بين السلاسل",
    "bridge protocol": "بروتوكول الجسر",
    "oracle": "أوراكل",
    "oracles": "أوراكل",

    # ── مصطلحات عامة ──
    "inflows": "تدفقات داخلة",
    "outflows": "تدفقات خارجة",
    "deposits": "إيداعات",
    "withdrawals": "سحوبات",
    "whales": "الحيتان",
    "total supply": "الإصدار الكلي",
    "circulating supply": "الإصدار المتداول",
    "fully diluted": "الإصدار الكلي المخفف",
    "dilution": "تخفيف",
    "fiat": "نقدي",
    "off-chain": "خارج السلسلة",
    "on-chain": "على السلسلة",
    "on-chain data": "بيانات على السلسلة",
    "downtime": "توقف",
    "outage": "انقطاع",
    "circuit breaker": "قاطع الدائرة",
    "pause": "إيقاف مؤقت",
    "unpause": "استئناف",
    "cancellation": "إلغاء",
    "emergency": "طوارئ",
    "roadmap": "خارطة الطريق",
    "partnership": "شراكة",
    "collaboration": "تعاون",
    "integration": "تكامل",
    "adoption": "اعتماد",
    "mainstream adoption": "اعتماد واسع",
    "mass adoption": "اعتماد جماهيري",
    "integration": "تكامل",
    "collaboration": "تعاون",
    "announcement": "إعلان",
    "report": "تقرير",
    "analysis": "تحليل",
    "forecast": "توقعات",
    "prediction": "توقع",
    "outlook": "توقعات",
    "guidance": "توجيهات",
    "benchmark": "معيار",
    "milestone": "معلم",
    "record": "رقم قياسي",
    "break record": "كسر رقم قياسي",
    "weekly": "أسبوعي",
    "monthly": "شهري",
    "quarterly": "ربع سنوي",
    "annually": "سنوي",
    "year-to-date": "منذ بداية العام",
    "year over year": "عام بعد عام",
    "month over month": "شهر بعد شهر",

    # ── مصطلحات الميم والتعبيرات ──
    "buy the dip": "اشترِ الهبوط",
    "diamond hands": "أيدٍ ماسية",
    "paper hands": "أيدٍ ورقية",
    "to the moon": "إلى القمر",
    "wen moon": "متى القمر",
    "ngmi": "لن تحققها",
    "wagmi": "سنحققها جميعاً",
    "gm": "صباح الخير",
    "fud": "خوف وشك",
    "fomo": "الخوف من فوات الفرصة",
    "rekt": "مُدمَّر",
    "hodl": "احتفظ",
    "bagholder": "حامل الخسائر",
    "ape in": "دخول أعمى",
    "dca": "شراء منتظم",
    "dollar cost averaging": "شراء منتظم",

    # ── عبارات شائعة في الأخبار ──
    "according to": "وفقاً لـ",
    "announced that": "أعلن أن",
    "revealed that": "كشف أن",
    "confirmed that": "أكد أن",
    "reported that": "أفاد أن",
    "stated that": "صرح أن",
    "noted that": "لفت أن",
    "pointed out": "أشار إلى",
    "highlighted": "أبرز",
    "emphasized": "شدد على",
    "speculated": "توقع",
    "estimated": "قدّر",
    "projected": "توقع",
    "anticipated": "توقع",
    "remains unchanged": "بقي بدون تغيير",
    "remains stable": "بقي مستقراً",
    "gained traction": "حصل على زخم",
    "lost momentum": "فقد الزخم",
    "gained popularity": "حصل على شعبية",
    "lost value": "فقد من قيمته",
    "gained value": "حقق قيمة",
    "outperformed": "تفوق على",
    "underperformed": "تأخر عن",
    "in a statement": "في بيان",
    "in a report": "في تقرير",
    "press release": "بيان صحفي",
    "blog post": "مقال مدونة",
    "social media": "وسائل التواصل",
    "market participants": "مشاركو السوق",
    "market sentiment": "معنويات السوق",
    "market conditions": "ظروف السوق",
    "market dynamics": "ديناميكيات السوق",
    "price action": "حركة السعر",
    "price movement": "حركة السعر",
    "price surge": "قفزة سعرية",
    "price drop": "انخفاض سعري",
    "price rally": "ارتفاع سعري",
    "price correction": "تصحيح سعري",
    "price decline": "تراجع سعري",
    "price increase": "زيادة سعرية",
    "significant": "كبير",
    "substantial": "جوهري",
    "notable": "ملحوظ",
    "remarkable": "استثنائي",
    "massive": "ضخم",
    "minor": "طفيف",
    "moderate": "معتدل",
    "sharp": "حاد",
    "gradual": "تدريجي",
    "steady": "ثابت",
    "rapid": "سريع",
    "sudden": "مفاجئ",
    "unexpected": "غير متوقع",
    "anticipated": "متوقع",
    "investors": "المستثمرون",
    "traders": "المتداولون",
    "analysts": "المحللون",
    "experts": "الخبراء",
    "enthusiasts": "المناصرون",
    "critics": "المنتقدون",
    "supporters": "المؤيدون",
    "opponents": "المعارضون",
    "regulators": "المنظمون",
    "lawmakers": "صناع القوانين",
    "policymakers": "صناع السياسات",
    "authorities": "السلطات",
    "officials": "المسؤولون",
    "industry": "القطاع",
    "sector": "القطاع",
    "space": "المجال",
    "landscape": "المشهد",
    "ecosystem": "النظام البيئي",
    "community": "المجتمع",
    "platform": "المنصة",
    "network": "الشبكة",
    "protocol": "البروتوكول",
    "project": "المشروع",
    "initiative": "المبادرة",
    "program": "البرنامج",
    "scheme": "الخطة",
    "framework": "الإطار",
    "legislation": "التشريع",
    "bill": "مشروع قانون",
    "provision": "بند",
    "compliance": "الامتثال",
    "enforcement": "الإنفاذ",
    "penalty": "عقوبة",
    "fine": "غرامة",
    "lawsuit": "دعوى قضائية",
    "settlement": "تسوية",
    "verdict": "حكم",
    "ruling": "قرار",
    "appeal": "استئناف",
    "investigation": "تحقيق",
    "inquiry": "استفسار",
    "probe": "تحقيق",
    "crackdown": "حملة",
    "ban": "حظر",
    "banned": "محظور",
    "prohibited": "ممنوع",
    "restricted": "مقيّد",
    "imposed sanctions": "فرض عقوبات",
    "lifted sanctions": "رفع عقوبات",
    "revoked": "ملغى",
    "suspended": "معلّق",
    "approved": "مُوافق عليه",
    "rejected": "مرفوض",
    "granted": "مُمنح",
    "denied": "مرفوض",
    "licensed": "مرخّص",
    "unlicensed": "غير مرخّص",
    "legal": "قانوني",
    "illegal": "غير قانوني",
    "legitimate": "مشروع",
    "fraudulent": "احتيالي",

    # ── تعبيرات زمنية ──
    "this week": "هذا الأسبوع",
    "last week": "الأسبوع الماضي",
    "next week": "الأسبوع القادم",
    "this month": "هذا الشهر",
    "last month": "الشهر الماضي",
    "next month": "الشهر القادم",
    "this year": "هذا العام",
    "last year": "العام الماضي",
    "next year": "العام القادم",
    "recently": "مؤخراً",
    "previously": "سابقاً",
    "currently": "حالياً",
    "shortly": "قريباً",
    "soon": "قريباً",
    "upcoming": "القادم",
    "ongoing": "مستمر",
    "pending": "معلّق",
    "completed": "مكتمل",
    "cancelled": "ملغى",
    "delayed": "متأخر",
    "postponed": "مؤجل",
    "scheduled": "مجدول",
    "expected": "متوقع",
    "earlier": "في وقت سابق",
    "later": "لاحقاً",
    "meanwhile": "في غضون ذلك",
    "subsequently": "لاحقاً",
    "following": "بعد",
    "prior to": "قبل",
    "as of": "اعتباراً من",
    "during": "خلال",
    "after": "بعد",
    "before": "قبل",
    "between": "بين",
    "despite": "رغم",
    "although": "على الرغم من",
    "however": "ومع ذلك",
    "moreover": "علاوة على ذلك",
    "furthermore": "بالإضافة إلى ذلك",
    "additionally": "إضافة إلى ذلك",
    "therefore": "لذلك",
    "consequently": "وبالتالي",
    "meanwhile": "في غضون ذلك",

    # ── مصطلحات إضافية ──
    "seed round": "جولة بذرة",
    "series a": "جولة A",
    "series b": "جولة B",
    "series c": "جولة C",
    "funding round": "جولة تمويل",
    "venture capital": "رأس مال مخاطر",
    "initial coin offering": "عرض أولي للعملات",
    "initial exchange offering": "عرض أولي على المنصة",
    "security token": "توكن أوراق مالية",
    "utility token": "توكن منفعة",
    "governance token": "توكن حوكمة",
    "memecoin": "عملة ميم",
    "altcoin": "عملة بديلة",
    "stablecoin": "عملة مستقرة",
    "privacy coin": "عملة خاصة",
    "payment token": "توكن دفع",
    "exchange token": "توكن منصة",
    "platform token": "توكن منصة",
    "play-to-earn": "العب لتربح",
    "gamefi": "ألعاب كريبتو",
    "socialfi": "تواصل اجتماعي كريبتو",
    "depin": "بنية تحتية لامركزية",
    "real world assets": "أصول حقيقية",
    "tokenized": "مُرمَّز",
    "tokenization": "الترميز",
    " fractional ownership": "ملكية جزئية",
    "real yield": "عائد حقيقي",
    "synthetic asset": "أصل صناعي",
    "derivatives": "المشتقات",
    "perpetual futures": "عقود دائمة",
    "binary options": "خيارات ثنائية",
    "prediction market": "سوق التوقعات",
    "copy trading": "التداول بالنسخ",
    "bot trading": "التداول بالبوت",
    "algorithmic trading": "التداول الخوارزمي",
    "high frequency trading": "التداول عالي التردد",
    "narrative": "السرديات",
    "rotation": "التناوب",
    "sector rotation": "تناوب القطاعات",
    "capital inflow": "تدفق رأسمالي",
    "capital outflow": "تدفق رأسمالي خارج",
    "net inflows": "صافي التدفقات الداخلة",
    "net outflows": "صافي التدفقات الخارجة",
    "record inflows": "تدفقات قياسية داخلة",
    "record outflows": "تدفقات قياسية خارجة",
    "consecutive": "متتالي",
    "for the first time": "لأول مرة",
    "all-time record": "رقم قياسي تاريخي",
    "multi-year high": "أعلى مستوى في سنوات",
    "multi-year low": "أدنى مستوى في سنوات",
    "year-to-date high": "أعلى مستوى منذ بداية العام",
    "year-to-date low": "أدنى مستوى منذ بداية العام",
    "weekly close": "إغلاق أسبوعي",
    "monthly close": "إغلاق شهري",
    "closed above": "أغلق أعلى من",
    "closed below": "أغلق أدنى من",
    "broke above": "اخترق أعلى من",
    "broke below": "اخترق أدنى من",
    "trading at": "يتداول عند",
    "priced at": "مُسعّر عند",
    "valued at": "مُثمّن عند",
    "worth": "قيمته",
    "approximately": "تقريباً",
    "roughly": "تقريباً",
    "nearly": "تقريباً",
    "almost": "تقريباً",
    "exactly": "تحديداً",
    "precisely": "بشكل دقيق",
    "at least": "على الأقل",
    "at most": "على الأكثر",
    "more than": "أكثر من",
    "less than": "أقل من",
    "over": "أكثر من",
    "under": "أقل من",
    "above": "أعلى من",
    "below": "أدنى من",
    "surpass": "يتجاوز",
    "exceed": "يتجاوز",
    "reach": "يصل",
    "decline": "تراجع",
    "drop": "انخفاض",
    "fall": "هبوط",
    "rise": "صعود",
    "growth": "نمو",
    "increase": "زيادة",
    "decrease": "انخفاض",
    "shrink": "تقلص",
    "expand": "توسع",
    "recover": "يتعافى",
    "bounce back": "يرتد",
    "stabilize": "يستقر",
    "stabilized": "استقر",
    "stabilizing": "في طور الاستقرار",
    "volatile": "متقلب",
    "volatility": "تقلب",
    "uncertainty": "عدم يقين",
    "turbulence": "اضطراب",
    "turmoil": "فوضى",
    "crisis": "أزمة",
    "confidence": "ثقة",
    "optimism": "تفاؤل",
    "pessimism": "تشاؤم",
    "concern": "قلق",
    "enthusiasm": "حماس",
    "caution": "حذر",
    "skepticism": "شك",
    "optimistic": "متفائل",
    "pessimistic": "متشائم",
    "cautious": "حذر",
    "confident": "واثق",
    "uncertain": "غير مؤكد",
}


# ═══════════════════════════════════════════════════════════
# 🌐 خريطة أسماء الكيانات بالعربي
# ═══════════════════════════════════════════════════════════
# تُستخدم لترجمة أسماء العملات والمنصات عند الاستعادة بعد الترجمة
# الأسماء اللي ما نبي نترجمها (رموز مثل BTC, ETH) مش موجودة هنا
ENTITY_AR_NAMES = {
    # ── عملات رئيسية ──
    "bitcoin": "بيتكوين", "btc": "بيتكوين", "bitcoin cash": "بيتكوين كاش",
    "bch": "بيتكوين كاش", "ethereum": "إيثيريوم", "eth": "إيثيريوم",
    "ether": "إيثر", "ethereum classic": "إيثيريوم كلاسيك", "etc": "إيثيريوم كلاسيك",
    "solana": "سولانا", "sol": "سولانا", "xrp": "ريبل", "ripple": "ريبل",
    "cardano": "كاردانو", "ada": "كاردانو", "dogecoin": "دوجكوين", "doge": "دوجكوين",
    "avalanche": "أفالانش", "avax": "أفالانش", "polkadot": "بولكادوت", "dot": "بولكادوت",
    "chainlink": "شاين لينك", "link": "شاين لينك", "polygon": "بوليجون", "matic": "بوليجون",
    "litecoin": "لايتكوين", "ltc": "لايتكوين", "tron": "ترون", "trx": "ترون",
    "uniswap": "يوني سواب", "aave": "إيفي", "near protocol": "نير بروتوكول",
    "near": "نير", "aptos": "أبتوس", "apt": "أبتوس",
    "arbitrum": "أربيتروم", "arb": "أربيتروم", "optimism": "أوبتيميزم", "op": "أوبتيميزم",
    "sui": "سوي", "sei": "سي", "pepe": "بيبي", "shiba": "شيبا", "shib": "شيبا",
    "toncoin": "تونكوين", "ton": "تون",
    "fantom": "فانتوم", "ftm": "فانتوم", "cosmos": "كوزموس", "atom": "كوزموس",
    "stellar": "ستيلار", "xlm": "ستيلار", "hedera": "هيدرا", "hbar": "هيدرا",
    "binance coin": "باينانس كوين", "bnb": "باينانس كوين",
    "usdt": "تيثر", "tether": "تيثر", "usdc": "يوس دي سي",
    "dai": "داي", "monero": "مونيرو", "xmr": "مونيرو",
    "tezos": "تيزوس", "xtz": "تيزوس", "vechain": "فيشين", "vet": "فيشين",
    "filecoin": "فيلكوين", "fil": "فيلكوين", "zcash": "زد كاش", "zec": "زد كاش",
    "eos": "إيوس", "algorand": "ألغوراند", "algo": "ألغوراند",
    "flow": "فلو", "kaspa": "كاسبا", "kas": "كاسبا",
    "worldcoin": "ورلد كوين", "wld": "ورلد كوين",
    "starknet": "ستارك نت", "strk": "ستارك نت",
    "celestia": "سيليستيا", "tia": "سيليستيا",
    "injective": "إنجيكتف", "inj": "إنجيكتف",
    "render": "ريندر", "rndr": "ريندر",
    "thorchain": "ثور تشين", "rune": "رن",
    "jupiter": "جوبيتر", "jup": "جوبيتر", "raydium": "ريديوم", "ray": "ريديوم",
    "drift": "دريفت", "hyperliquid": "هايبر ليكويد", "hype": "هايبر ليكويد",
    "eigenlayer": "إيجن لاير", "eigen": "إيجن",
    "etherfi": "إيثر فاي", "ethfi": "إيثر فاي",
    "renzo": "رينزو", "pendle": "بندل",
    "ondo": "أوندو", "berachain": "بيرا تشين", "bera": "بيرا تشين",
    "sonic": "سونيك", "virtuals": "فيرتشوالز",
    "bittensor": "بيتنسور", "tao": "بيتنسور",
    "bonk": "بونك", "wif": "ويف", "floki": "فلولكي",
    "decentraland": "ديسنترالاند", "mana": "ديسنترالاند",
    "sandbox": "ساند بوكس", "sand": "ساند بوكس",
    "maker": "ميكر", "mkr": "ميكر", "lido": "ليدو", "ldo": "ليدو",
    "curve": "كيرف", "crv": "كيرف", "synthetix": "سينثيتيكس", "snx": "سينثيتيكس",
    "compound": "كومباوند", "comp": "كومباوند",
    "gmx": "جي إم إكس", "dydx": "دي واي دي إكس",
    "jito": "جيتو", "morpho": "مورفو", "aerodrome": "أيرو دروم", "aero": "أيرو دروم",
    "fetch.ai": "فيتش أيه", "fet": "فيتش",
    # ─ـ منصات ──
    "binance": "بايننس", "coinbase": "كوين بيس",
    "kraken": "كراكن", "bybit": "باي بت", "okx": "أو كي إكس", "kucoin": "كوكوين",
    "bitfinex": "بتفينيكس", "bitstamp": "بت ستامب", "gemini": "جيميني",
    "bitget": "بتجيت", "mexc": "إم إكس سي",
    "upbit": "أوبت", "bithumb": "بيثامب", "deribit": "ديربت",
    "crypto.com": "كريبتو دوت كوم", "huobi": "هويوبي", "htx": "إتش تي إكس",
    "opensea": "أوبن سي", "metamask": "ميتا ماسك",
    "ledger": "ليجر", "trezor": "تريزور",
    "pancakeswap": "بان كيك سواب", "sushiswap": "سوشي سواب",
    # ─ـ شركات ومؤسسات ──
    "blackrock": "بلاك روك", "black rock": "بلاك روك",
    "fidelity": "فيديليتي", "grayscale": "غري سكيل",
    "microstrategy": "مايكرو استراتيجي", "strategy": "مايكرو استراتيجي",
    "bitwise": "بت وايز", "vaneck": "فان إيك",
    "invesco": "إنفيسكو", "21shares": "توينتي ون شيرز",
    "proshares": "برو شيرز", "galaxy digital": "غالاكسي ديجيتال",
    "coinshares": "كوين شيرز", "blockstream": "بلوك ستريم",
    "consensys": "كونسينسيس", "circle": "سيركل", "paxos": "باكسوس",
    "paypal": "باي بال", "visa": "فيزا", "mastercard": "ماستركارد",
    # ─ـ أشخاص ──
    "satoshi": "ساتوشي", "vitalik": "فيتاليك", "buterin": "فيتاليك",
    "saylor": "سيلور", "musk": "إيلون ماسك",
    "changpeng zhao": "تشانغ بينغ تشاو", "cz": "سي زد",
    "dorsey": "جاك دورسي", "gensler": "جينسلر",
    "powell": "باول", "yellen": "يلين",
    "brian armstrong": "برايان أرمسترونغ", "garlinghouse": "جارلينغ هاوس",
    "sam bankman-fried": "سام بانكمان فرايد", "sbf": "إس بي إف",
    # ─ـ منظمين ──
    "sec": "هيئة الأوراق المالية", "cftc": "هيئة تداول السلع",
    "federal reserve": "الاحتياطي الفيدرالي", "fomc": "لجنة السوق الفيدرالية",
    # ── مصادر الأخبار ──
    "coindesk": "كوين ديسك", "cointelegraph": "كوين تيليغراف",
    "decrypt": "ديكريبت", "beincrypto": "بي إن كريبتو",
    "coinpedia": "كوين بيديا", "blockworks": "بلوك ووركس",
    "bitcoinist": "بيتكوينيست", "crypto.news": "كريبتو نيوز",
}

# بناء نسخة lowercase للبحث السريع
_ENTITY_AR_LOWER = {k.lower(): v for k, v in ENTITY_AR_NAMES.items()}

def _protect_entities(text: str) -> Tuple[str, Dict[str, Tuple[str, Optional[str]]]]:
    """حماية الكيانات المهمة قبل الترجمة — نستبدلها بعلامات مؤقتة
    نستخدم حدود الكلمات لمنع المطابقة الجزئية.
    نحمي أيضاً الجمع بإضافة s/es بعد الاسم.
    """
    restore_map = {}
    protected = text
    counter = 0

    all_terms = []
    for term, trans in GLOSSARY_AR.items():
        all_terms.append((term, trans))
    for term in CRITICAL_NAMES:
        if term not in GLOSSARY_AR:
            # بحث عن ترجمة عربية من ENTITY_AR_NAMES
            ar_name = _ENTITY_AR_LOWER.get(term.lower(), None)
            all_terms.append((term, ar_name))

    # ترتيب حسب الطول (الأطول أولاً لمنع التداخل)
    all_terms.sort(key=lambda x: len(x[0]), reverse=True)

    for term, trans in all_terms:
        # حماية الكلمة مع حدود الكلمات
        pattern = re.compile(r'(\b|[^a-zA-Z])' + re.escape(term) + r'(\b|[^a-zA-Z])', re.IGNORECASE)
        matches = list(pattern.finditer(protected))
        if matches:
            for match in reversed(matches):
                # احتفظ بالأحرف المحيطة
                prefix = match.group(1) if match.group(1) else ""
                suffix = match.group(2) if match.group(2) else ""
                placeholder = f"§§{counter:03d}§§"
                protected = protected[:match.start()] + prefix + placeholder + suffix + protected[match.end():]
                restore_map[placeholder] = (match.group(0).strip(), trans)
                counter += 1

    # حماية إضافية: صيغ الجمع الشائعة لأسماء العملات والبروتوكولات
    plural_terms = [
        "bitcoins", "ethereums", "altcoins", "stablecoins", "memecoins",
        "shitcoins", "tokens", "coins", "nfts", "etfs", "daos",
        "hackers", "whales", "investors", "traders", "validators",
        "miners", "exchanges", "wallets", "bridges", "oracles",
        "blockchains", "protocols", "platforms", "networks", "ecosystems",
        "inflows", "outflows", "deposits", "withdrawals",
        "regulators", "lawmakers", "officials", "authorities",
        "futures", "options", "swaps", "pools",
        "contracts", "transactions", "blocks",
    ]
    for term in plural_terms:
        if term in GLOSSARY_AR:
            continue
        pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)
        matches = list(pattern.finditer(protected))
        if matches:
            for match in reversed(matches):
                placeholder = f"§§{counter:03d}§§"
                protected = protected[:match.start()] + placeholder + protected[match.end():]
                restore_map[placeholder] = (match.group(0), None)
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
