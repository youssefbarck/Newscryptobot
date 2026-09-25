# -*- coding: utf-8 -*-
"""
طبقة قاعدة البيانات — تعمل على Postgres (Neon) وSQLite بنفس الكود.

المخطط:
- processed_messages : سجل كل منشور مُلتقط مع حالته (pending/processed/published/failed/ignored)
- published_items    : الأخبار المنشورة فعلياً + نصوصها المطبّعة لاكتشاف التشابه
- channel_watermarks : آخر message_id تمت تغطيته لكل قناة مصدر (Watermark Polling)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

log = logging.getLogger("db")

STATES = ("pending", "processed", "published", "failed", "ignored")


def utcnow() -> datetime:
    """وقت UTC بدون معلومات المنطقة الزمنية — متوافق مع SQLite وPostgres معاً."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# ---------------------------------------------------------------- engine

def normalize_database_url(url: Optional[str], data_dir: Path) -> str:
    """توحيد صيغة DATABASE_URL لتعمل مع SQLAlchemy async على الحالتين."""
    if not url:
        data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{(data_dir / 'state.db').as_posix()}"
    url = url.strip()
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    elif url.startswith("sqlite:///"):
        url = "sqlite+aiosqlite:///" + url.split(":///", 1)[1]
    if url.startswith("sqlite+aiosqlite:///"):
        db_file = url.split("sqlite+aiosqlite:///", 1)[1]
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    return url


def create_engine(db_url: str) -> AsyncEngine:
    kwargs: dict = {"echo": False}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    return create_async_engine(db_url, **kwargs)


# ---------------------------------------------------------------- models

class Base(DeclarativeBase):
    pass


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    __table_args__ = (
        UniqueConstraint("source_channel_id", "source_message_id", name="uq_channel_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_channel_id: Mapped[str] = mapped_column(String(64), index=True)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    source_name: Mapped[Optional[str]] = mapped_column(String(128))
    raw_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    ignore_reason: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    final_text: Mapped[Optional[str]] = mapped_column(Text)
    ticker: Mapped[Optional[str]] = mapped_column(String(32))
    media_type: Mapped[Optional[str]] = mapped_column(String(16))
    has_media: Mapped[int] = mapped_column(Integer, default=0)  # 0/1 لضمان التوافق
    error: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PublishedItem(Base):
    __tablename__ = "published_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_raw: Mapped[str] = mapped_column(Text, default="")
    normalized_final: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[Optional[str]] = mapped_column(Text)
    source_channel_id: Mapped[Optional[str]] = mapped_column(String(64))
    dest_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ChannelWatermark(Base):
    __tablename__ = "channel_watermarks"

    source_channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_message_id: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- repository

class Repository:
    """كل عمليات القراءة/الكتابة — الجلسة تُفتح وتُغلق داخل كل دالة (أمان أعلى)."""

    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    # ---------------- منشورات قيد المعالجة ----------------

    async def record_items(self, rows: List[dict]) -> List[int]:
        """
        تسجيل دفعة عناصر كـ pending دفعة واحدة (قبل ترقية الـ Watermark).
        يُتجاهل الصف إذا كان موجوداً مسبقاً (نفس القناة + نفس message_id).
        يعيد معرفات الصفوف الجديدة فقط.
        """
        if not rows:
            return []
        new_ids: List[int] = []
        async with self._session_factory() as session, session.begin():
            for row in rows:
                exists = await session.execute(
                    select(ProcessedMessage.id).where(
                        ProcessedMessage.source_channel_id == row["source_channel_id"],
                        ProcessedMessage.source_message_id == row["source_message_id"],
                    )
                )
                if exists.scalar() is not None:
                    continue
                obj = ProcessedMessage(**row)
                session.add(obj)
                await session.flush()
                new_ids.append(obj.id)
        return new_ids

    async def load_rows(self, row_ids: Sequence[int]) -> List[ProcessedMessage]:
        if not row_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProcessedMessage).where(ProcessedMessage.id.in_(list(row_ids)))
            )
            rows = list(result.scalars().all())
        rows.sort(key=lambda r: r.id)
        return rows

    async def mark_state(self, row_id: int, state: str, **fields) -> None:
        if state not in STATES:
            raise ValueError(f"حالة غير معروفة: {state}")
        values = {"state": state, "updated_at": utcnow()}
        for key in ("ignore_reason", "title", "final_text", "ticker", "error", "retry_count"):
            if key in fields:
                values[key] = fields[key]
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(ProcessedMessage).where(ProcessedMessage.id == row_id).values(**values)
            )

    async def fetch_retryable(
        self, max_retries: int, max_age_hours: int, batch_size: int
    ) -> List[ProcessedMessage]:
        """
        صفوف تستحق إعادة المحاولة:
        - حالة pending (بقايا انهيار) أو failed مع retry_count < الحد
        - صفوف processed القديمة تُترك (تفضيل تكرار نادر على تكرار النشر — موثّق في README)
        - الأقدم من max_age_hours يُهمل تلقائياً كـ stale
        """
        cutoff = utcnow() - timedelta(hours=max_age_hours)
        stale_ids: List[int] = []
        retryable: List[ProcessedMessage] = []
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProcessedMessage)
                .where(
                    ProcessedMessage.state.in_(["pending", "failed"]),
                    ProcessedMessage.retry_count < max_retries,
                )
                .order_by(ProcessedMessage.id.asc())
                .limit(batch_size * 3)
            )
            rows = list(result.scalars().all())
        for row in rows:
            if row.created_at and row.created_at < cutoff:
                stale_ids.append(row.id)
            else:
                retryable.append(row)
            if len(retryable) >= batch_size:
                break
        for row_id in stale_ids:
            await self.mark_state(row_id, "ignored", ignore_reason="stale: تجاوز الحد الزمني للنشر")
        return retryable

    # ---------------- الأخبار المنشورة (لاكتشاف التشابه) ----------------

    async def recent_published(self, window_hours: int, limit: int = 500) -> List[Tuple[int, str, str]]:
        """[(id, normalized_raw, normalized_final)] خلال النافذة الزمنية."""
        cutoff = utcnow() - timedelta(hours=window_hours)
        async with self._session_factory() as session:
            result = await session.execute(
                select(PublishedItem.id, PublishedItem.normalized_raw, PublishedItem.normalized_final)
                .where(PublishedItem.published_at >= cutoff)
                .order_by(PublishedItem.id.desc())
                .limit(limit)
            )
            return [(r[0], r[1] or "", r[2] or "") for r in result.all()]

    async def find_published_by_hash(self, content_hash: str) -> Optional[int]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PublishedItem.id).where(PublishedItem.content_hash == content_hash).limit(1)
            )
            return result.scalar()

    async def add_published(
        self,
        content_hash: str,
        normalized_raw: str,
        normalized_final: str,
        title: Optional[str],
        source_channel_id: str,
        dest_message_id: Optional[int],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                PublishedItem(
                    content_hash=content_hash,
                    normalized_raw=normalized_raw,
                    normalized_final=normalized_final,
                    title=title,
                    source_channel_id=source_channel_id,
                    dest_message_id=dest_message_id,
                    published_at=utcnow(),
                )
            )

    # ---------------- العلامات المائية (Watermarks) ----------------

    async def get_watermark(self, source_channel_id: str) -> Optional[int]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ChannelWatermark.last_message_id).where(
                    ChannelWatermark.source_channel_id == source_channel_id
                )
            )
            return result.scalar()

    async def set_watermark(self, source_channel_id: str, last_message_id: int) -> None:
        async with self._session_factory() as session, session.begin():
            existing = await session.execute(
                select(ChannelWatermark.source_channel_id).where(
                    ChannelWatermark.source_channel_id == source_channel_id
                )
            )
            if existing.scalar() is None:
                session.add(
                    ChannelWatermark(
                        source_channel_id=source_channel_id, last_message_id=last_message_id
                    )
                )
            else:
                await session.execute(
                    update(ChannelWatermark)
                    .where(ChannelWatermark.source_channel_id == source_channel_id)
                    .values(last_message_id=last_message_id, updated_at=utcnow())
                )

    # ---------------- الصيانة والإحصاء ----------------

    async def housekeeping(self, retention_days: int) -> Dict[str, int]:
        """حذف السجلات الأقدم من فترة الاحتفاظ — يبقي قاعدة Neon المجانية خفيفة."""
        cutoff = utcnow() - timedelta(days=retention_days)
        deleted: Dict[str, int] = {}
        async with self._session_factory() as session, session.begin():
            r1 = await session.execute(
                delete(ProcessedMessage).where(
                    ProcessedMessage.state.in_(["published", "ignored", "failed"]),
                    ProcessedMessage.created_at < cutoff,
                )
            )
            r2 = await session.execute(
                delete(PublishedItem).where(PublishedItem.published_at < cutoff)
            )
            deleted["processed_messages"] = r1.rowcount or 0
            deleted["published_items"] = r2.rowcount or 0
        return deleted

    async def counts_by_state(self) -> Dict[str, int]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProcessedMessage.state, func.count(ProcessedMessage.id)).group_by(
                    ProcessedMessage.state
                )
            )
            return {state: count for state, count in result.all()}
