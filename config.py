# -*- coding: utf-8 -*-
"""
تحميل وقراءة إعدادات النظام.

- الإعدادات التشغيلية من settings.yaml (قابل للتعديل مباشرة في GitHub).
- الأسرار من متغيرات البيئة (GitHub Secrets / ملف .env محلياً).
- أولويات التجاوز: متغيرات البيئة > settings.yaml > القيم الافتراضية.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import yaml
from dotenv import load_dotenv

# جذر المستودع (مجلد المشروع)
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class ConfigError(Exception):
    """خطأ في الإعدادات برسالة عربية واضحة تشرح الحل."""


# ---------------------------------------------------------------- dataclasses

@dataclass
class MediaSettings:
    enabled: bool = True
    max_media_mb: int = 40
    include_media_only_posts: bool = False


@dataclass
class ProcessingSettings:
    rewrite_enabled: bool = True
    min_post_length: int = 80
    max_post_length: int = 4000
    max_body_chars: int = 900
    strict_numbers: bool = False
    media: MediaSettings = field(default_factory=MediaSettings)


@dataclass
class DedupSettings:
    similarity_threshold: float = 86.0
    window_hours: int = 72


@dataclass
class LimitsSettings:
    max_posts_per_minute: int = 4
    max_posts_per_run: int = 10
    post_delay_seconds: int = 8


@dataclass
class FiltersSettings:
    ignore_keywords: List[str] = field(default_factory=list)
    ignore_channels: List[str] = field(default_factory=list)


@dataclass
class SyncSettings:
    fetch_limit_per_channel: int = 30
    on_first_run: str = "skip_to_latest"  # skip_to_latest | process_backlog


@dataclass
class AISettings:
    model: str = "gemini-2.0-flash"
    temperature: float = 0.3
    max_output_tokens: int = 1500
    timeout_seconds: int = 60
    max_retries: int = 3


@dataclass
class RetriesSettings:
    max_retries: int = 3
    max_age_hours: int = 24
    batch_size: int = 10


@dataclass
class HousekeepingSettings:
    enabled: bool = True
    retention_days: int = 30


@dataclass
class Settings:
    source_channels: List[str]
    destination_channel: str
    post_template: str
    auto_join: bool
    processing: ProcessingSettings
    dedup: DedupSettings
    limits: LimitsSettings
    filters: FiltersSettings
    sync: SyncSettings
    ai: AISettings
    retries: RetriesSettings
    housekeeping: HousekeepingSettings
    data_dir: Path = DEFAULT_DATA_DIR


@dataclass
class Secrets:
    """الأسرار القادمة من متغيرات البيئة فقط — لا توضع أبداً في settings.yaml."""
    telegram_api_id: int
    telegram_api_hash: str
    telegram_session: str
    gemini_api_key: str
    database_url: Optional[str]

    def masked_summary(self) -> str:
        """ملخص آمن للطباعة في السجلات (بدون قيم الأسرار)."""
        return (
            f"TELEGRAM_API_ID={self.telegram_api_id}, "
            f"TELEGRAM_API_HASH={'مضبوط' if self.telegram_api_hash else 'مفقود'}, "
            f"TELEGRAM_SESSION={'مضبوطة' if self.telegram_session else 'مفقودة'}, "
            f"GEMINI_API_KEY={'مضبوط' if self.gemini_api_key else 'مفقود'}, "
            f"DATABASE_URL={'مضبوط' if self.database_url else 'غير مضبوط (وضع SQLite)'}"
        )


# ---------------------------------------------------------------- helpers

def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "نعم")


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    return [str(p).strip() for p in value if str(p).strip()]


def _section(data: dict, name: str) -> dict:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


DEFAULT_POST_TEMPLATE = "📰 <b>{title}</b>\n\n{body}\n\n{ticker_line}📌 المصدر: {source}\n"


# ---------------------------------------------------------------- loaders

def _load_settings(path: Optional[str]) -> Settings:
    """قراءة settings.yaml مع تحويل أنواع البيانات بأمان."""
    settings_path = Path(path) if path else (REPO_ROOT / "settings.yaml")
    if not settings_path.exists():
        raise ConfigError(
            f"ملف الإعدادات غير موجود: {settings_path}\n"
            f"تأكد من وجود settings.yaml في جذر المستودع."
        )
    try:
        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"خطأ في صيغة YAML داخل {settings_path.name}:\n{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"ملف {settings_path.name} فارغ أو بصيغة غير صحيحة.")

    processing = _section(raw, "processing")
    sync = _section(raw, "sync")
    if str(sync.get("on_first_run", "skip_to_latest")) not in ("skip_to_latest", "process_backlog"):
        raise ConfigError("sync.on_first_run يقبل القيمتين فقط: skip_to_latest أو process_backlog")

    settings = Settings(
        source_channels=_as_str_list(raw.get("source_channels")),
        destination_channel=str(raw.get("destination_channel", "")).strip(),
        post_template=str(raw.get("post_template") or DEFAULT_POST_TEMPLATE),
        auto_join=_as_bool(raw.get("auto_join"), True),
        processing=ProcessingSettings(
            rewrite_enabled=_as_bool(processing.get("rewrite_enabled"), True),
            min_post_length=_as_int(processing.get("min_post_length"), 80),
            max_post_length=_as_int(processing.get("max_post_length"), 4000),
            max_body_chars=_as_int(processing.get("max_body_chars"), 900),
            strict_numbers=_as_bool(processing.get("strict_numbers"), False),
            media=MediaSettings(
                enabled=_as_bool(_section(processing, "media").get("enabled"), True),
                max_media_mb=_as_int(_section(processing, "media").get("max_media_mb"), 40),
                include_media_only_posts=_as_bool(
                    _section(processing, "media").get("include_media_only_posts"), False
                ),
            ),
        ),
        dedup=DedupSettings(
            similarity_threshold=_as_float(_section(raw, "dedup").get("similarity_threshold"), 86.0),
            window_hours=_as_int(_section(raw, "dedup").get("window_hours"), 72),
        ),
        limits=LimitsSettings(
            max_posts_per_minute=_as_int(_section(raw, "limits").get("max_posts_per_minute"), 4),
            max_posts_per_run=_as_int(_section(raw, "limits").get("max_posts_per_run"), 10),
            post_delay_seconds=_as_int(_section(raw, "limits").get("post_delay_seconds"), 8),
        ),
        filters=FiltersSettings(
            ignore_keywords=_as_str_list(_section(raw, "filters").get("ignore_keywords")),
            ignore_channels=_as_str_list(_section(raw, "filters").get("ignore_channels")),
        ),
        sync=SyncSettings(
            fetch_limit_per_channel=_as_int(sync.get("fetch_limit_per_channel"), 30),
            on_first_run=str(sync.get("on_first_run", "skip_to_latest")),
        ),
        ai=AISettings(
            model=str(_section(raw, "ai").get("model") or "gemini-2.0-flash"),
            temperature=_as_float(_section(raw, "ai").get("temperature"), 0.3),
            max_output_tokens=_as_int(_section(raw, "ai").get("max_output_tokens"), 1500),
            timeout_seconds=_as_int(_section(raw, "ai").get("timeout_seconds"), 60),
            max_retries=_as_int(_section(raw, "ai").get("max_retries"), 3),
        ),
        retries=RetriesSettings(
            max_retries=_as_int(_section(raw, "retries").get("max_retries"), 3),
            max_age_hours=_as_int(_section(raw, "retries").get("max_age_hours"), 24),
            batch_size=_as_int(_section(raw, "retries").get("batch_size"), 10),
        ),
        housekeeping=HousekeepingSettings(
            enabled=_as_bool(_section(raw, "housekeeping").get("enabled"), True),
            retention_days=_as_int(_section(raw, "housekeeping").get("retention_days"), 30),
        ),
    )

    # تجاوزات اختيارية من متغيرات البيئة (مفيدة دون تعديل الملف)
    env_sources = os.environ.get("SOURCE_CHANNELS", "").strip()
    if env_sources:
        settings.source_channels = _as_str_list(env_sources)
    env_dest = os.environ.get("DESTINATION_CHANNEL", "").strip()
    if env_dest:
        settings.destination_channel = env_dest

    return settings


def _env_first(*names: str) -> str:
    """أول قيمة موجودة وغير فارغة من قائمة أسماء متغيرات بيئة (طبقة توافق الأسماء)."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return ""


# أسماء بديلة شائعة للأسرار — يعمل النظام مع أي منها دون تعديل الـ Workflow لديك
ALIASES = {
    "TELEGRAM_API_ID": ("TELEGRAM_API_ID", "API_ID", "TG_API_ID", "TELEGRAM_API"),
    "TELEGRAM_API_HASH": ("TELEGRAM_API_HASH", "API_HASH", "TG_API_HASH"),
    "TELEGRAM_SESSION": (
        "TELEGRAM_SESSION", "SESSION", "STRING_SESSION",
        "TELETHON_SESSION", "TG_SESSION", "TELEGRAM_SESSION_STRING",
    ),
    "GEMINI_API_KEY": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_API_KEY", "GEMINI_KEY"),
    "DATABASE_URL": ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL", "NEON_DATABASE_URL", "NEON_URL"),
}


def _load_secrets() -> Secrets:
    secrets = Secrets(
        telegram_api_id=_as_int(_env_first(*ALIASES["TELEGRAM_API_ID"]), 0),
        telegram_api_hash=_env_first(*ALIASES["TELEGRAM_API_HASH"]),
        telegram_session=_env_first(*ALIASES["TELEGRAM_SESSION"]),
        gemini_api_key=_env_first(*ALIASES["GEMINI_API_KEY"]),
        database_url=_env_first(*ALIASES["DATABASE_URL"]) or None,
    )
    return secrets


def validate(settings: Settings, secrets: Secrets, needs_ai: bool = True) -> None:
    """تحقق شامل قبل التشغيل — يرفع ConfigError برسالة تحل المشكلة."""
    missing: List[str] = []
    if not secrets.telegram_api_id:
        missing.append("TELEGRAM_API_ID")
    if not secrets.telegram_api_hash:
        missing.append("TELEGRAM_API_HASH")
    if not secrets.telegram_session:
        missing.append("TELEGRAM_SESSION")
    if needs_ai and settings.processing.rewrite_enabled and not secrets.gemini_api_key:
        missing.append("GEMINI_API_KEY")

    if missing:
        alias_hint = "\n".join(
            f"  • {name} ← الأسماء المقبولة: {', '.join(ALIASES[name])}"
            for name in missing if name in ALIASES
        )
        raise ConfigError(
            "متغيرات بيئة ناقصة: " + ", ".join(missing) + "\n"
            "→ على GitHub: Settings → Secrets and variables → Actions → New repository secret\n"
            "→ محلياً: انسخ .env.example إلى .env وعبّئ القيم.\n"
            + ("→ الأسماء البديلة المقبولة (لأنماط متعددة من الـ Workflows):\n" + alias_hint + "\n"
               if alias_hint else "")
            + "للتذكير: TELEGRAM_SESSION تُولَّد مرة واحدة عبر:  python scripts/login.py"
        )

    if not settings.source_channels:
        raise ConfigError(
            "لا توجد قنوات مصدر.\n"
            "→ أضف قناة واحدة على الأقل إلى source_channels داخل settings.yaml (مثال: \"@CoinDesk\")."
        )
    if not settings.destination_channel:
        raise ConfigError(
            "قناة النشر غير مضبوطة.\n"
            "→ ضع اسم قناتك في destination_channel داخل settings.yaml (مثال: \"@my_news\").\n"
            "→ ويجب أن يكون الحساب صاحب الجلسة أدمن فيها بصلاحية نشر الرسائل."
        )
    for placeholder in ("{title}", "{body}", "{source}"):
        if placeholder not in settings.post_template:
            raise ConfigError(
                f"قالب المنشور post_template لا يحتوي على المتغير الإلزامي {placeholder}."
            )
    if settings.processing.rewrite_enabled and not needs_ai and not secrets.gemini_api_key:
        raise ConfigError("إعادة الصياغة مفعّلة لكن GEMINI_API_KEY مفقود.")


def load_config(settings_file: Optional[str] = None) -> tuple[Settings, Secrets]:
    """نقطة الدخول: تحميل الإعدادات والأسرار معاً."""
    load_dotenv(REPO_ROOT / ".env", override=False)  # محلياً فقط؛ لا أثر على Actions
    settings = _load_settings(settings_file or os.environ.get("SETTINGS_FILE"))
    secrets = _load_secrets()
    return settings, secrets
