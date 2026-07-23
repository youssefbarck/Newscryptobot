"""
🐋 Whale News Bot v3 - قاعدة البيانات المحلية
━━━━━━━━━━━━━━━━━━━━━━━━━━━━══━━━━━━━━━━━━━━━━
تخزين منظم للأخبار — لا Hash فقط بل حقائق كاملة
"""

import os, json, time, hashlib, logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict

log = logging.getLogger("WhaleBot")


# ═══════════════════════════════════════════════════════════
# 📰 سجل الخبر في قاعدة البيانات
# ═══════════════════════════════════════════════════════════
@dataclass
class NewsRecord:
    """سجل خبر في قاعدة البيانات — يُستخدم لكشف التكرار"""
    title: str = ""
    fact_hash: str = ""        # hash الحقائق (كيانات + عملات)
    text_hash: str = ""         # hash النص (فحص سريع للتكرار)
    entities: List[str] = field(default_factory=list)
    coins: List[str] = field(default_factory=list)
    news_type: str = ""
    source: str = ""
    timestamp: float = 0.0
    published: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "NewsRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class NewsDatabase:
    """قاعدة بيانات الأخبار المحلية — JSON-based"""

    def __init__(self, persist_dir: str = "/tmp"):
        self._records: Dict[str, NewsRecord] = {}   # fact_hash → record
        self._text_hashes: Set[str] = set()         # text_hash set
        self._persist_dir = persist_dir
        self._file = os.path.join(persist_dir, "news_db.json")
        self._max_records = 2000
        self._max_age = 86400 * 7  # 7 أيام

    def load(self):
        """تحميل البيانات من القرص"""
        try:
            with open(self._file, "r") as f:
                data = json.load(f)
            for rec_data in data.get("records", []):
                rec = NewsRecord.from_dict(rec_data)
                self._records[rec.fact_hash] = rec
                self._text_hashes.add(rec.text_hash)
            log.info(f"📂 Loaded {len(self._records)} records from DB")
        except Exception as e:
            log.warning(f"DB load failed: {e}")

    def save(self):
        """حفظ البيانات على القرص"""
        try:
            self._cleanup()
            data = {"records": [r.to_dict() for r in self._records.values()]}
            with open(self._file, "w") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            log.warning(f"DB save failed: {e}")

    def _cleanup(self):
        """تنظيف السجلات القديمة"""
        now = time.time()
        old_keys = [
            k for k, r in self._records.items()
            if now - r.timestamp > self._max_age
        ]
        for k in old_keys:
            self._text_hashes.discard(self._records[k].text_hash)
            del self._records[k]
        # إذا تجاوز الحد — احذف الأقدم
        if len(self._records) > self._max_records:
            sorted_keys = sorted(
                self._records.keys(),
                key=lambda k: self._records[k].timestamp
            )
            to_remove = len(self._records) - self._max_records
            for k in sorted_keys[:to_remove]:
                self._text_hashes.discard(self._records[k].text_hash)
                del self._records[k]

    def is_duplicate(self, text_hash: str, fact_hash: str = "") -> bool:
        """فحص التكرار: hash النص أولاً، ثم hash الحقائق"""
        # فحص سريع بنص العنوان
        if text_hash in self._text_hashes:
            return True
        # فحص عميق بالحقائق
        if fact_hash and fact_hash in self._records:
            return True
        return False

    def add(self, record: NewsRecord):
        """إضافة سجل جديد"""
        self._records[record.fact_hash] = record
        self._text_hashes.add(record.text_hash)

    def mark_published(self, fact_hash: str):
        """تعليم سجل كمنشور"""
        if fact_hash in self._records:
            self._records[fact_hash].published = True

    def get_by_fact_hash(self, fact_hash: str) -> Optional[NewsRecord]:
        """جلب سجل بـ fact_hash"""
        return self._records.get(fact_hash)

    def get_stats(self) -> Dict:
        """إحصائيات قاعدة البيانات"""
        total = len(self._records)
        published = sum(1 for r in self._records.values() if r.published)
        types = {}
        sources = {}
        for r in self._records.values():
            types[r.news_type] = types.get(r.news_type, 0) + 1
            sources[r.source] = sources.get(r.source, 0) + 1
        return {
            "total": total,
            "published": published,
            "types": types,
            "sources": sources,
        }

    def find_similar(self, fact_hash: str, entities: List[str], coins: List[str]) -> Optional[NewsRecord]:
        """بحث عن سجلات مشابهة بالكيانات والعملات"""
        # إذا تطابقت الكيانات الرئيسية مع سجل موجود → نفس الخبر
        for existing_hash, record in self._records.items():
            if existing_hash == fact_hash:
                continue
            if time.time() - record.timestamp > 86400:  # أقدم من يوم → تجاهل
                continue
            entity_overlap = len(set(entities) & set(record.entities))
            coin_overlap = len(set(coins) & set(record.coins))
            if entity_overlap >= 2 or (entity_overlap >= 1 and coin_overlap >= 1):
                return record
        return None


# ═══════════════════════════════════════════════════════════
# 📊 إحصائيات النشر (Analytics)
# ═══════════════════════════════════════════════════════════
class Analytics:
    """إحصائيات النشر — تُستخدم لتعلم أي الأخبار أفضل"""

    def __init__(self, persist_dir: str = "/tmp"):
        self._file = os.path.join(persist_dir, "analytics.json")
        self._data: Dict = {
            "total_collected": 0,
            "total_published": 0,
            "total_rejected": 0,
            "by_source": {},
            "by_type": {},
            "daily_stats": {},
        }

    def load(self):
        try:
            with open(self._file, "r") as f:
                self._data = json.load(f)
        except:
            pass

    def save(self):
        try:
            with open(self._file, "w") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except:
            pass

    def record_collected(self, source: str, news_type: str):
        self._data["total_collected"] += 1
        self._data["by_source"][source] = self._data["by_source"].get(source, 0) + 1
        self._data["by_type"][news_type] = self._data["by_type"].get(news_type, 0) + 1

    def record_published(self, source: str, news_type: str, score: float):
        self._data["total_published"] += 1

    def record_rejected(self, reason: str):
        self._data["total_rejected"] += 1

    def get_daily_summary(self) -> Dict:
        return {
            "collected": self._data["total_collected"],
            "published": self._data["total_published"],
            "rejected": self._data["total_rejected"],
            "publish_rate": (
                self._data["total_published"] / self._data["total_collected"] * 100
                if self._data["total_collected"] > 0 else 0
            ),
            "by_source": self._data["by_source"],
            "by_type": self._data["by_type"],
        }

