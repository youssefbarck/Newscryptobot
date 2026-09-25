# -*- coding: utf-8 -*-
"""تهيئة السجلات — تنسيق موحد بأوقات UTC يظهر بوضوح في سجل GitHub Actions."""
from __future__ import annotations

import logging
import os
import time


class _UTCFormatter(logging.Formatter):
    converter = time.gmtime  # كل الطوابع الزمنية بتوقيت UTC


def setup_logging(level: str | None = None) -> None:
    chosen = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(
        _UTCFormatter("%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(chosen)

    # تقليل ضجيج المكتبات الخارجية
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
