# -*- coding: utf-8 -*-
"""إنشاء عميل Telethon وحل القنوات."""
from __future__ import annotations

import logging
import re

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel

from bot.config import Settings, Secrets

log = logging.getLogger("telegram.client")


def create_client(secrets: Secrets) -> TelegramClient:
    """عميل بجلسة StringSession (نفس الجلسة تعمل على Actions والمحلي)."""
    client = TelegramClient(
        StringSession(secrets.telegram_session),
        secrets.telegram_api_id,
        secrets.telegram_api_hash,
        device_model="news-bot",
        system_version="1.0",
        app_version="1.0",
        flood_sleep_threshold=0,  # نتحكم بـ FloodWait يدوياً في publisher
    )
    client.parse_mode = "html"  # القالب يستخدم وسوم <b> وغيرها
    return client


def normalize_channel_ref(ref: str) -> str:
    """توحيد صيغة مرجع القناة: روابط t.me → @username، الأرقام تبقى كما هي."""
    ref = ref.strip()
    ref = re.sub(r"^https?://", "", ref, flags=re.IGNORECASE)
    ref = re.sub(r"^t\.me/", "", ref, flags=re.IGNORECASE)
    ref = ref.strip("/")
    if ref.isdigit() or ref.startswith("-"):
        return ref
    if not ref.startswith("@"):
        ref = "@" + ref
    return ref


async def resolve_channel(client: TelegramClient, ref: str, auto_join: bool) -> Channel:
    """
    حل مرجع القناة إلى كيان فعلي.
    يرفع RuntimeError برسالة عربية واضحة إذا تعذر الوصول للقناة.
    """
    normalized = normalize_channel_ref(ref)
    entity = None
    try:
        if normalized.lstrip("@").isdigit() or normalized.startswith("-"):
            entity = await client.get_entity(int(normalized))
        else:
            entity = await client.get_entity(normalized)
    except Exception as first_error:  # noqa: BLE001
        # محاولة أخيرة: الانضمام أولاً ثم الحل (مفيد للقنوات العامة غير المنضمة)
        if auto_join and normalized.startswith("@"):
            try:
                log.info("محاولة الانضمام إلى %s ثم إعادة الحل...", normalized)
                await client(JoinChannelRequest(normalized))
                entity = await client.get_entity(normalized)
            except Exception as second_error:  # noqa: BLE001
                raise RuntimeError(
                    f"تعذر الوصول إلى القناة {ref} ({type(second_error).__name__}: {second_error}). "
                    f"تأكد أن القناة عامة وأن اليوزرنيم صحيح، أو استخدم اليوزرنيم بدل المعرف الرقمي."
                ) from second_error
        else:
            raise RuntimeError(
                f"تعذر الوصول إلى القناة {ref} ({type(first_error).__name__}: {first_error}). "
                f"تأكد أن القناة عامة أو أن الحساب منضم إليها."
            ) from first_error

    if not isinstance(entity, Channel):
        raise RuntimeError(f"المرجع {ref} لا يشير إلى قناة (النوع: {type(entity).__name__}).")
    return entity
