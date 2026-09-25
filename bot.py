#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نقطة التشغيل الجذرية — متوافقة مع بيئتك الحالية على GitHub Actions.

إذا كان الـ Workflow لديك ينفّذ:  python bot.py
فإنه سيستمر بالعمل كما هو تماماً — لكن الآن يدير المحرك الاحترافي الكامل
(bot/ package): Watermark Polling، منع التكرار بطبقات، إعادة صياغة Gemini
مع فحص الأرقام، إدارة حالات، وإعادة محاولات تلقائية.

المسار المكافئ:  python -m bot.main
"""
import sys
from pathlib import Path

# ضمان إيجاد حزمة bot بجانب هذا الملف مهما كان مجلد التشغيل
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot.main import main  # noqa: E402

if __name__ == "__main__":
    main()
