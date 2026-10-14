# -*- coding: utf-8 -*-
"""🎯 نقطة دخول بوت أخبار الكريبتو — النسخة المفككة لملفات متعددة.

التشغيل:
    python main.py             ← جولة كاملة (إرسال فعلي)
    python main.py --dry-run   ← طباعة الرسائل دون إرسال
    python main.py --test      ← رسالة تجربة للتحقق من الإعداد
    python main.py --doctor    ← فحص تشخيصي: التوكن والقناة والصلاحيات
"""
import argparse
import asyncio
import logging
import sys

import bot as bot_mod

log = logging.getLogger("NewsBot")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def main(argv=None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(description="بوت أخبار الكريبتو 🐋")
    parser.add_argument("--dry-run", action="store_true", help="طباعة الرسائل دون إرسال")
    parser.add_argument("--test", action="store_true", help="إرسال رسالة تجربة فقط")
    parser.add_argument("--doctor", action="store_true", help="فحص تشخيصي شامل")
    parser.add_argument("--limit", type=int, default=None, help="أقصى عدد أخبار في الجولة")
    parser.add_argument("--min-score", type=int, default=None, help="حد فلتر الجودة (1-10)")
    args = parser.parse_args(argv)

    try:
        if args.doctor:
            return asyncio.run(bot_mod.run_doctor(dry_run=args.dry_run))
        if args.test:
            return asyncio.run(bot_mod.send_test(dry_run=args.dry_run))
        return asyncio.run(bot_mod.run_cycle(dry_run=args.dry_run,
                                             limit=args.limit,
                                             min_score=args.min_score))
    except KeyboardInterrupt:
        log.info("🛑 توقف يدوي")
        return 130


if __name__ == "__main__":
    sys.exit(main())
