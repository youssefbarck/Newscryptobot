# -*- coding: utf-8 -*-
"""كتابة ملخص التشغيلة إلى GitHub Step Summary (يظهر في صفحة الـ Workflow)."""
from __future__ import annotations

import logging
import os
from typing import Dict, List

log = logging.getLogger("summary")


def write_run_summary(
    counters_dict: Dict[str, int],
    published_titles: List[str],
    sources_count: int,
    database_label: str,
) -> None:
    lines = [
        "## 📊 ملخص تشغيل بوت الأخبار",
        "",
        f"- **قنوات المصدر:** {sources_count}",
        f"- **قاعدة البيانات:** {database_label}",
        "",
        "| النتيجة | العدد |",
        "|---|---|",
        f"| ✅ نُشر | {counters_dict.get('published', 0)} |",
        f"| 🚫 تجاهل | {counters_dict.get('ignored', 0)} |",
        f"| ❌ فشل | {counters_dict.get('failed', 0)} |",
        f"| ↩️ إعادة محاولة | {counters_dict.get('retried', 0)} |",
        f"| ⏭️ موجود مسبقاً | {counters_dict.get('skipped_existing', 0)} |",
    ]
    if published_titles:
        lines += ["", "### الأخبار المنشورة", ""]
        lines += [f"- {t}" for t in published_titles[:20]]

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            return
        except OSError as exc:
            log.warning("تعذر كتابة الملخص: %s", exc)
    # خارج Actions: طباعة ملخص مصغر في السجل
    log.info("ملخص: %s", counters_dict)
