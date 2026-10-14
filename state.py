# -*- coding: utf-8 -*-
"""ذاكرة منع التكرار — بصمات الأخبار المرسلة تُحفظ في ملف JSON يُرفع للمستودع"""
import json
import logging
import os
import time

from .analysis import similar
from .config import DEDUP_DAYS

log = logging.getLogger("crypto-bot")


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict) and isinstance(state.get("seen"), dict):
            return state
    except (OSError, ValueError):
        pass
    return {"seen": {}}


def already_seen(item: dict, state: dict) -> bool:
    """بصمة مطابقة؟ أو عنوان شبيه جدًا بخبر أُرسل سابقًا؟"""
    for h in item["hashes"]:
        if h in state["seen"]:
            return True
    norm = item["norm"]
    for rec in state["seen"].values():
        if rec.get("norm") and similar(norm, rec["norm"]):
            return True
    return False


def mark(item: dict, state: dict) -> None:
    now = int(time.time())
    rec = {"ts": now, "norm": item["norm"]}
    for h in item["hashes"]:
        state["seen"][h] = rec


def save_state(path: str, state: dict) -> None:
    """تقليم البصمات الأقدم من DEDUP_DAYS ثم الحفظ."""
    cutoff = time.time() - DEDUP_DAYS * 86400
    state["seen"] = {h: r for h, r in state["seen"].items()
                     if isinstance(r, dict) and r.get("ts", 0) >= cutoff}
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        log.info("💾 سجل التكرار محفوظ (%s بصمة)", len(state["seen"]))
    except OSError as exc:
        log.warning("تعذر حفظ السجل: %s", exc)
