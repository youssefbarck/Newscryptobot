# -*- coding: utf-8 -*-
"""🧹 ذاكرة منع التكرار — بصمات الأخبار المرسلة في JSON يُرفع للمستودع.

من الملف القديم: هاش MD5 للعنوان المُطبّع + تشابه Jaccard.
مطوّر بصمات رابط الخبر + تقليم تلقائي كل DEDUP_DAYS يومًا.
"""
import hashlib
import json
import logging
import os
import re
import time

from config import DEDUP_DAYS, DEDUP_FILE
from quality import similar

log = logging.getLogger("NewsBot")


def compute_hash(title: str) -> str:
    """هاش مبني على العنوان المُطبّع (أول 100 حرف)."""
    norm = re.sub(r"[^\w\s\u0600-\u06FF]", "", title.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.md5(norm[:100].encode()).hexdigest()[:12]


def item_hashes(item) -> list[str]:
    """بصمتان: من العنوان المُطبّع ومن رابط الخبر."""
    hashes = [compute_hash(item.title)]
    if item.link:
        path = re.sub(r"[?#].*$", "", item.link)
        hashes.append("u" + hashlib.md5(path.encode()).hexdigest()[:15])
    return hashes


def load_hashes() -> dict:
    """تحميل الحالة — {الهاش: {ts, norm}}."""
    try:
        with open(DEDUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("seen"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"seen": {}}


def is_duplicate(item, state: dict, recent_norms: list[str]) -> bool:
    """فحص شامل: بصمة مباشرة + تشابه مع أرشيف البصمات + تشابه داخل الجولة."""
    for h in item.hashes:
        if h in state["seen"]:
            log.info("🧹 بصمة مطابقة: %s", item.title[:60])
            return True
    for rec in state["seen"].values():
        if rec.get("norm") and similar(item.norm, rec["norm"]):
            log.info("🧹 شبيه بأرشيف: %s", item.title[:60])
            return True
    for prev in recent_norms:
        if similar(item.norm, prev):
            log.info("🧹 شبيه داخل الجولة: %s", item.title[:60])
            return True
    return False


def mark(item, state: dict) -> None:
    rec = {"ts": int(time.time()), "norm": item.norm}
    for h in item.hashes:
        state["seen"][h] = rec


def save_hashes(state: dict) -> None:
    """تقليم البصمات الأقدم من DEDUP_DAYS (بحد أقصى 3000) ثم الحفظ."""
    cutoff = time.time() - DEDUP_DAYS * 86400
    seen = {h: r for h, r in state["seen"].items()
            if isinstance(r, dict) and r.get("ts", 0) >= cutoff}
    if len(seen) > 3000:
        keep = sorted(seen.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)[:3000]
        seen = dict(keep)
    state["seen"] = seen
    directory = os.path.dirname(DEDUP_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(DEDUP_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        log.info("💾 سجل التكرار محفوظ (%s بصمة) → %s", len(seen), DEDUP_FILE)
    except OSError as exc:
        log.warning("تعذر حفظ السجل: %s", exc)
