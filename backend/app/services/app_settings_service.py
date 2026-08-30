from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting

AUTO_SCHEDULE_ENABLED_KEY = "auto_schedule_enabled"
DEFAULT_SCHEDULE_WINDOW_KEY = "default_schedule_window"
SCHEDULER_SCAN_INTERVAL_KEY = "scheduler_scan_interval_seconds"
DISPATCH_JITTER_MIN_KEY = "dispatch_jitter_min_seconds"
DISPATCH_JITTER_MAX_KEY = "dispatch_jitter_max_seconds"
MANUAL_REVIEW_MODE_KEY = "manual_review_mode"
WEBHOOK_URL_KEY = "webhook_url"
ADMIN_TOKEN_KEY = "admin_token"


def get_setting_str(db: Session, key: str, default: str = "") -> str:
    setting = db.get(AppSetting, key)
    if setting is None or setting.value is None:
        return default
    return setting.value


def set_setting_str(db: Session, key: str, value: str) -> None:
    setting = db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value


def get_setting_int(db: Session, key: str, default: int) -> int:
    val = get_setting_str(db, key, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def set_setting_int(db: Session, key: str, value: int) -> None:
    set_setting_str(db, key, str(value))


def get_setting_bool(db: Session, key: str, default: bool) -> bool:
    val = get_setting_str(db, key, "")
    if not val:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


def set_setting_bool(db: Session, key: str, value: bool) -> None:
    set_setting_str(db, key, "true" if value else "false")


def is_auto_schedule_enabled(db: Session) -> bool:
    return get_setting_bool(db, AUTO_SCHEDULE_ENABLED_KEY, get_settings().scheduler_enabled)


def set_auto_schedule_enabled(db: Session, enabled: bool) -> bool:
    set_setting_bool(db, AUTO_SCHEDULE_ENABLED_KEY, enabled)
    db.commit()
    return enabled


def get_default_schedule_window(db: Session) -> str:
    return get_setting_str(db, DEFAULT_SCHEDULE_WINDOW_KEY, get_settings().default_schedule_window)


def get_scheduler_scan_interval(db: Session) -> int:
    return get_setting_int(db, SCHEDULER_SCAN_INTERVAL_KEY, get_settings().scheduler_scan_interval_seconds)


def get_dispatch_jitter_min(db: Session) -> int:
    return get_setting_int(db, DISPATCH_JITTER_MIN_KEY, get_settings().dispatch_jitter_min_seconds)


def get_dispatch_jitter_max(db: Session) -> int:
    return get_setting_int(db, DISPATCH_JITTER_MAX_KEY, get_settings().dispatch_jitter_max_seconds)


def is_manual_review_mode(db: Session) -> bool:
    return get_setting_bool(db, MANUAL_REVIEW_MODE_KEY, get_settings().manual_review_mode)


def get_webhook_url(db: Session) -> str:
    return get_setting_str(db, WEBHOOK_URL_KEY, "")


def get_admin_token(db: Session) -> str:
    return get_setting_str(db, ADMIN_TOKEN_KEY, get_settings().admin_token)
