# -*- coding: utf-8 -*-
"""
النشر في قناة الوجهة — مع حد أدنى للفاصل الزمني وسقف للدقيقة وحماية من FloodWait.

- الوسائط: تنزيل إلى مجلد مؤقت ثم إرسال مع الخبر كتعليق (Caption ≤ 1024 حرف).
- إذا كان النص أطول من حد التعليق: تُنشر الوسائط أولاً ثم النص برسالة منفصلة.
- أي فشل في الوسائط (قناة محمية مثلاً) لا يضيع الخبر: يُنشر نصياً فقط.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from bot.config import MediaSettings
from bot.monitor import NewsItem

log = logging.getLogger("telegram.publisher")

CAPTION_LIMIT = 1024


class RateLimiter:
    """حد أقصى للمنشورات في الدقيقة + فاصل إلزامي بين كل منشورين."""

    def __init__(self, per_minute: int, delay_seconds: int):
        self.per_minute = max(1, per_minute)
        self.delay_seconds = max(0, delay_seconds)
        self._timestamps: deque = deque()
        self._last_send: float = 0.0

    async def wait_slot(self) -> None:
        while True:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > 60:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.per_minute:
                sleep_for = 60 - (now - self._timestamps[0]) + 0.25
                log.info("بلوغ حد الدقيقة (%s/دقيقة) — انتظار %.1fs", self.per_minute, sleep_for)
                await asyncio.sleep(sleep_for)
                continue
            gap = time.monotonic() - self._last_send
            if self.delay_seconds and gap < self.delay_seconds:
                await asyncio.sleep(self.delay_seconds - gap)
            self._last_send = time.monotonic()
            self._timestamps.append(time.monotonic())
            return


async def _send_with_flood_retry(factory, attempts: int = 3):
    """تنفيذ إرسال مع التعامل مع FloodWait (انتظار فعلي حتى 120 ثانية)."""
    last_exc: Optional[Exception] = None
    for _ in range(attempts):
        try:
            return await factory()
        except FloodWaitError as exc:
            wait = min(exc.seconds + 1, 120)
            log.warning("FloodWait من Telegram: انتظار %ss", wait)
            last_exc = exc
            await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _media_size_mb(msg: Message) -> float:
    try:
        media = msg.media
        doc = getattr(media, "document", None)
        if doc is not None and getattr(doc, "size", None):
            return doc.size / (1024 * 1024)
        photo = getattr(media, "photo", None)
        if photo is not None and getattr(photo, "file_size", None):
            return photo.file_size / (1024 * 1024)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


class Publisher:
    def __init__(self, client: TelegramClient, dest_entity, media_settings: MediaSettings,
                 rate_limiter: RateLimiter, tmp_dir: Path):
        self.client = client
        self.dest = dest_entity
        self.media_settings = media_settings
        self.limiter = rate_limiter
        self.tmp_dir = tmp_dir
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    async def publish(self, item: NewsItem, final_text: str) -> int:
        """نشر الخبر. يعيد message_id في قناة الوجهة."""
        await self.limiter.wait_slot()

        files: List[str] = []
        if self.media_settings.enabled and item.media_messages:
            files = await self._download_media(item)

        try:
            if files:
                captions = [final_text if len(final_text) <= CAPTION_LIMIT else ""] + [""] * (len(files) - 1)
                sent = await _send_with_flood_retry(
                    lambda: self.client.send_file(
                        self.dest, files, caption=captions, link_preview=False
                    )
                )
                dest_id = sent[0].id if isinstance(sent, list) else sent.id
                if len(final_text) > CAPTION_LIMIT:
                    msg2 = await _send_with_flood_retry(
                        lambda: self.client.send_message(self.dest, final_text, link_preview=False)
                    )
                    dest_id = msg2.id
                return dest_id

            msg = await _send_with_flood_retry(
                lambda: self.client.send_message(self.dest, final_text, link_preview=False)
            )
            return msg.id
        finally:
            self._cleanup(files)

    async def _download_media(self, item: NewsItem) -> List[str]:
        """تنزيل وسائط العنصر مع احترام حد الحجم — أي فشل يعيد قائمة فارغة (نشر نصي)."""
        paths: List[str] = []
        for index, msg in enumerate(item.media_messages[:10]):  # سقف أمان للألبومات
            size_mb = _media_size_mb(msg)
            if size_mb > self.media_settings.max_media_mb:
                log.warning("تجاهل وسائط %s بحجم %.1fMB (الحد %sMB)", item.max_message_id,
                            size_mb, self.media_settings.max_media_mb)
                continue
            try:
                path = await self.client.download_media(
                    msg, file=os.path.join(self.tmp_dir, f"{item.max_message_id}_{index}")
                )
                if path and os.path.exists(path):
                    paths.append(str(path))
            except Exception as exc:  # noqa: BLE001 — قنوات محمية/روابط منتهية
                log.warning("فشل تنزيل وسائط من #%s (%s: %s) — سيُنشر النص فقط",
                            item.max_message_id, type(exc).__name__, exc)
        return paths

    @staticmethod
    def _cleanup(paths: List[str]) -> None:
        for path in paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
