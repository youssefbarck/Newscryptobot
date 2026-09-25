# -*- coding: utf-8 -*-
"""
المراقبة بأسلوب Watermark Polling:

- لكل قناة نحفظ آخر message_id تمت تغطيته.
- كل تشغيلة تجلب فقط المنشورات الأحدث من العلامة (min_id) بترتيب تصاعدي.
- أول تشغيل: القفز لآخر منشور بدون معالجة (skip_to_latest) حتى لا تُنشر الأخبار القديمة.
- الألبومات (Albums) تُجمع كوحدة واحدة عبر grouped_id.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from telethon import TelegramClient
from telethon.tl.types import (
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
)

from bot.config import Settings
from bot.db import Repository

log = logging.getLogger("telegram.monitor")


@dataclass
class NewsItem:
    """وحدة معالجة واحدة: منشور مفرد أو ألبوم كامل."""
    source_channel_id: str
    source_name: str
    message_ids: List[int]
    text: str
    media_type: str  # none | photo | video | document | album
    media_messages: List[Message] = field(default_factory=list)

    @property
    def max_message_id(self) -> int:
        return max(self.message_ids)


def _media_type_of(msg: Message) -> Optional[str]:
    """تحديد نوع الوسائط — مع تجاهل معاينات الروابط والملصقات."""
    media = msg.media
    if media is None or isinstance(media, MessageMediaWebPage):
        return None
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc is None:
            return None
        for attr in doc.attributes or []:
            if isinstance(attr, DocumentAttributeSticker):
                return None  # الملصقات ليست محتوى إخبارياً
        if (doc.mime_type or "").startswith("video/"):
            return "video"
        if any(isinstance(a, DocumentAttributeVideo) for a in (doc.attributes or [])):
            return "video"
        if (doc.mime_type or "").startswith("image/"):
            return "photo"
        return "document"
    return None


def _build_items(channel_id: str, channel_name: str, messages: List[Message]) -> List[NewsItem]:
    """تحويل رسائل قناة واحدة إلى عناصر خبرية (مع تجميع الألبومات)."""
    items: List[NewsItem] = []
    groups: Dict[int, dict] = {}

    for msg in messages:  # مرتبة تصاعدياً (الأقدم أولاً)
        if msg.action is not None:
            continue  # رسائل خدمية (تغيير اسم، تثبيت...)
        text = (msg.message or "").strip()
        media_type = _media_type_of(msg)

        if msg.grouped_id is not None:
            bucket = groups.setdefault(
                int(msg.grouped_id),
                {"ids": [], "texts": [], "media": [], "types": set()},
            )
            bucket["ids"].append(msg.id)
            if text and text not in bucket["texts"]:
                bucket["texts"].append(text)
            if media_type:
                bucket["media"].append(msg)
                bucket["types"].add(media_type)
            continue

        items.append(
            NewsItem(
                source_channel_id=channel_id,
                source_name=channel_name,
                message_ids=[msg.id],
                text=text,
                media_type=media_type or "none",
                media_messages=[msg] if media_type else [],
            )
        )

    # إخراج الألبومات — تُعالج بعد رسائل المفرد حسب ترتيب وصولها
    for grouped_id, bucket in sorted(groups.items()):
        types = bucket["types"]
        if types:
            media_type = "album" if len(bucket["media"]) > 1 else types.pop()
        else:
            media_type = "none"
        items.append(
            NewsItem(
                source_channel_id=channel_id,
                source_name=channel_name,
                message_ids=bucket["ids"],
                text="\n".join(bucket["texts"]),
                media_type=media_type,
                media_messages=bucket["media"],
            )
        )

    items.sort(key=lambda i: i.max_message_id)
    return items


class Monitor:
    def __init__(self, client: TelegramClient, repo: Repository, settings: Settings):
        self.client = client
        self.repo = repo
        self.settings = settings

    async def ensure_watermarks(
        self, sources: Dict[str, object]
    ) -> None:
        """
        sources: {canonical_id: entity}
        أول تشغيل لكل قناة: وضع العلامة حسب سياسة on_first_run.
        """
        backlog_mode = self.settings.sync.on_first_run == "process_backlog"
        for channel_id, entity in sources.items():
            current = await self.repo.get_watermark(channel_id)
            if current is not None:
                continue
            if backlog_mode:
                await self.repo.set_watermark(channel_id, 0)
                log.info("قناة %s: وضع process_backlog — ستُعالج أحدث %s منشوراً",
                         channel_id, self.settings.sync.fetch_limit_per_channel)
                continue
            latest = await self.client.get_messages(entity, limit=1)
            latest_id = latest[0].id if latest else 0
            await self.repo.set_watermark(channel_id, latest_id)
            log.info("قناة %s: أول تشغيل — القفز إلى آخر منشور #%s بدون معالجة", channel_id, latest_id)

    async def fetch_new_items(
        self, sources: Dict[str, object], names: Dict[str, str]
    ) -> List[NewsItem]:
        """
        جلب كل ما هو أحدث من العلامة المائية لكل قناة (بحد fetch_limit_per_channel).
        يعيد عناصر مرتبة تصاعدياً عبر كل القنوات (الأقدم أولاً).
        """
        all_items: List[NewsItem] = []
        per_channel_limit = self.settings.sync.fetch_limit_per_channel

        for channel_id, entity in sources.items():
            watermark = await self.repo.get_watermark(channel_id) or 0
            messages: List[Message] = [
                msg
                async for msg in self.client.iter_messages(
                    entity, min_id=watermark, reverse=True, limit=per_channel_limit
                )
            ]
            if not messages:
                log.info("قناة %s: لا جديد فوق #%s", names.get(channel_id, channel_id), watermark)
                continue

            items = _build_items(channel_id, names.get(channel_id, channel_id), messages)
            newest = max(i.max_message_id for i in items)
            # ترقية العلامة المائية بعد اكتمال الجلب — المعالجة تحدث لاحقاً من القاعدة
            await self.repo.set_watermark(channel_id, newest)
            log.info(
                "قناة %s: جُلب %s عنصراً (منشورات #%s..#%s) — العلامة الآن #%s",
                names.get(channel_id, channel_id), len(items),
                min(m.id for m in messages), newest, newest,
            )
            all_items.extend(items)

        all_items.sort(key=lambda i: i.max_message_id)
        return all_items
