from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting

AUTO_SCHEDULE_ENABLED_KEY = "auto_schedule_enabled"


def is_auto_schedule_enabled(db: Session) -> bool:
    setting = db.get(AppSetting, AUTO_SCHEDULE_ENABLED_KEY)
    if setting is None:
        return get_settings().scheduler_enabled
    return setting.value.lower() in {"1", "true", "yes", "on"}


def set_auto_schedule_enabled(db: Session, enabled: bool) -> bool:
    setting = db.get(AppSetting, AUTO_SCHEDULE_ENABLED_KEY)
    if setting is None:
        setting = AppSetting(key=AUTO_SCHEDULE_ENABLED_KEY, value="true" if enabled else "false")
        db.add(setting)
    else:
        setting.value = "true" if enabled else "false"
    db.commit()
    return enabled
