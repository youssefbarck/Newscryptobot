"""
📊 Whale News Bot v2.0 — Source Quality Management System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
يُقيّم جودة كل مصدر RSS ويُعطّل المصادر السيئة تلقائيًا.
لا يحذف المصادر — يُعطّلها منطقيًا فقط (يمكن إعادة تفعيلها تلقائيًا).

القرص: source_quality.json
"""

import os, json, time, threading
from typing import Dict, List, Optional

from config import log


# ═══════════════════════════════════════════════════════════
# 💾 تخزين حالة المصادر
# ═══════════════════════════════════════════════════════════
_STORE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_quality.json"
)

# ثوابت التقييم
DEFAULT_SCORE = 100
MIN_SCORE = 0
MAX_SCORE = 100
PENALTY = 5       # خصم لكل خطأ
REWARD = 1        # مكافأة لكل خبر ناجح
DISABLE_THRESHOLD = 30          # تعطيل إن انخفضت النتيجة عن هذا
REJECTION_WINDOW = 20           # آخر N مقال للفحص
REJECTION_RATIO = 0.5           # أكثر من 50% مرفوض → تعطيل
RECOVERY_INTERVAL = 86400       # 24 ساعة بين محاولات الاسترداد
RECOVERY_TARGET = 50            # إعادة تفعيل عند وصول النتيجة لهذا


class SourceRecord:
    """سجل مصدر واحد — يُخزّن في JSON كـ dict"""

    def __init__(self, name: str):
        self.name: str = name
        self.score: int = DEFAULT_SCORE
        self.enabled: bool = True
        self.disabled_at: float = 0.0          # timestamp عند التعطيل
        self.last_recovery_attempt: float = 0.0
        self.recent_results: List[bool] = []   # True = نجاح، False = فشل
        self.total_published: int = 0
        self.total_rejected: int = 0

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "score": self.score,
            "enabled": self.enabled,
            "disabled_at": self.disabled_at,
            "last_recovery_attempt": self.last_recovery_attempt,
            "recent_results": self.recent_results[-REJECTION_WINDOW:],
            "total_published": self.total_published,
            "total_rejected": self.total_rejected,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SourceRecord":
        rec = cls(d.get("name", "unknown"))
        rec.score = max(MIN_SCORE, min(MAX_SCORE, d.get("score", DEFAULT_SCORE)))
        rec.enabled = d.get("enabled", True)
        rec.disabled_at = d.get("disabled_at", 0.0)
        rec.last_recovery_attempt = d.get("last_recovery_attempt", 0.0)
        rec.recent_results = d.get("recent_results", [])
        rec.total_published = d.get("total_published", 0)
        rec.total_rejected = d.get("total_rejected", 0)
        return rec


# ═══════════════════════════════════════════════════════════
# 🏭 Source Quality Manager
# ═══════════════════════════════════════════════════════════
class SourceQualityManager:
    """مدير جودة المصادر — singleton.

    يتعامل مع:
    - تقييم جودة كل مصدر
    - تعطيل المصادر السيئة
    - استرداد المصادر تلقائيًا
    """

    def __init__(self):
        self._sources: Dict[str, SourceRecord] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._save_counter = 0
        self._load()

    # ─── التخزين ───────────────────────────────────────────

    def _load(self):
        """تحميل البيانات من القرص"""
        try:
            if os.path.exists(_STORE_FILE):
                with open(_STORE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for name, rec_data in data.items():
                    if isinstance(rec_data, dict):
                        self._sources[name] = SourceRecord.from_dict(rec_data)
                log.info(f"📊 Source quality: {len(self._sources)} sources loaded")
        except Exception as e:
            log.warning(f"📊 Source quality load error: {e}")

    def _save(self):
        """حفظ البيانات على القرص"""
        try:
            data = {name: rec.to_dict() for name, rec in self._sources.items()}
            with open(_STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        except Exception as e:
            log.warning(f"📊 Source quality save error: {e}")

    def _maybe_save(self):
        """حفظ تلقائي كل 10 تغييرات"""
        self._dirty = True
        self._save_counter += 1
        if self._save_counter >= 10:
            self._save()
            self._save_counter = 0
            self._dirty = False

    def flush(self):
        """حفظ فوري"""
        with self._lock:
            if self._dirty:
                self._save()
                self._dirty = False

    # ─── الوصول ─────────────────────────────────────────────

    def _get_or_create(self, source_name: str) -> SourceRecord:
        """جلب سجل مصدر أو إنشاء واحد جديد"""
        if source_name not in self._sources:
            self._sources[source_name] = SourceRecord(source_name)
        return self._sources[source_name]

    def is_source_enabled(self, source_name: str) -> bool:
        """هل المصدر مفعّل؟ (للاستخدام في fetch_all_news)"""
        rec = self._sources.get(source_name)
        if rec is None:
            return True  # مصدر جديد — مفعّل افتراضيًا
        return rec.enabled

    def get_score(self, source_name: str) -> int:
        rec = self._sources.get(source_name)
        return rec.score if rec else DEFAULT_SCORE

    # ─── تعديل النتائج ─────────────────────────────────────

    def record_success(self, source_name: str):
        """مقال نُشر بنجاح — مكافأة +1"""
        with self._lock:
            rec = self._get_or_create(source_name)

            old_score = rec.score
            rec.score = min(MAX_SCORE, rec.score + REWARD)
            rec.total_published += 1
            rec.recent_results.append(True)

            # تقليم النتائج القديمة
            if len(rec.recent_results) > REJECTION_WINDOW:
                rec.recent_results = rec.recent_results[-REJECTION_WINDOW:]

            # تسجيل التغيير
            if old_score != rec.score:
                log.info(
                    f"📊 SOURCE SCORE | Source: {source_name} | "
                    f"Old: {old_score} | New: {rec.score} | Reason: Article published"
                )

            self._maybe_save()

    def record_rejection(self, source_name: str, reason: str = "unknown"):
        """مقال مُرفض أو معطوب — خصم -5"""
        with self._lock:
            rec = self._get_or_create(source_name)

            old_score = rec.score
            rec.score = max(MIN_SCORE, rec.score - PENALTY)
            rec.total_rejected += 1
            rec.recent_results.append(False)

            # تقليم النتائج القديمة
            if len(rec.recent_results) > REJECTION_WINDOW:
                rec.recent_results = rec.recent_results[-REJECTION_WINDOW:]

            log.info(
                f"📊 SOURCE SCORE | Source: {source_name} | "
                f"Old: {old_score} | New: {rec.score} | Reason: {reason}"
            )

            # فحص التعطيل التلقائي
            self._check_auto_disable(rec)

            self._maybe_save()

    def record_parse_failure(self, source_name: str, reason: str = "parse_error"):
        """فشل تحليل RSS — نفس معاملة الرفض"""
        self.record_rejection(source_name, reason)

    # ─── التعطيل التلقائي ──────────────────────────────────

    def _check_auto_disable(self, rec: SourceRecord):
        """فحص هل يجب تعطيل المصدر"""
        if not rec.enabled:
            return  # معطّل بالفعل

        should_disable = False
        reason = ""

        # الشرط 1: النتيجة أقل من 30
        if rec.score < DISABLE_THRESHOLD:
            should_disable = True
            reason = f"Quality score too low ({rec.score})"

        # الشرط 2: أكثر من 50% مرفوض من آخر 20
        elif len(rec.recent_results) >= 10:
            rejected_count = sum(1 for r in rec.recent_results if not r)
            total = len(rec.recent_results)
            ratio = rejected_count / total
            if ratio > REJECTION_RATIO:
                should_disable = True
                reason = f"Too many corrupted articles ({rejected_count}/{total})"

        if should_disable:
            rec.enabled = False
            rec.disabled_at = time.time()
            log.warning(
                f"📊 SOURCE DISABLED | Source: {rec.name} | Reason: {reason} | "
                f"Rejected: {rec.total_rejected} | Published: {rec.total_published} | "
                f"Quality Score: {rec.score}"
            )

    # ─── الاسترداد ───────────────────────────────────────────

    def should_attempt_recovery(self, source_name: str) -> bool:
        """هل حان وقت محاولة استرداد هذا المصدر؟"""
        rec = self._sources.get(source_name)
        if rec is None or rec.enabled:
            return False

        now = time.time()
        if now - rec.last_recovery_attempt < RECOVERY_INTERVAL:
            return False

        rec.last_recovery_attempt = now
        return True

    def recovery_success(self, source_name: str):
        """مقال نجح من مصدر معطّل — تحقق من إعادة التفعيل"""
        with self._lock:
            rec = self._get_or_create(source_name)

            old_score = rec.score
            rec.score = min(MAX_SCORE, rec.score + REWARD)
            rec.total_published += 1
            rec.recent_results.append(True)

            if len(rec.recent_results) > REJECTION_WINDOW:
                rec.recent_results = rec.recent_results[-REJECTION_WINDOW:]

            log.info(
                f"📊 RECOVERY | Source: {source_name} | "
                f"Old: {old_score} | New: {rec.score} | Target: {RECOVERY_TARGET}"
            )

            if rec.score >= RECOVERY_TARGET:
                rec.enabled = True
                rec.disabled_at = 0.0
                log.info(
                    f"📊 SOURCE RE-ENABLED | Source: {source_name} | "
                    f"Quality Score: {rec.score}"
                )

            self._maybe_save()

    # ─── التقرير ────────────────────────────────────────────

    def get_status_report(self) -> str:
        """تقرير حالة المصادر"""
        lines = ["📊 Source Quality Report", "━" * 30]
        for name, rec in sorted(self._sources.items()):
            status = "✅" if rec.enabled else "❌"
            recent = rec.recent_results[-REJECTION_WINDOW:]
            rej = sum(1 for r in recent if not r) if recent else 0
            total_recent = len(recent)
            lines.append(
                f"  {status} {name}: score={rec.score} | "
                f"published={rec.total_published} | rejected={rec.total_rejected} | "
                f"recent={rej}/{total_recent}"
            )
        return "\n".join(lines)


# ─── Singleton ───────────────────────────────────────────────
source_quality = SourceQualityManager()
