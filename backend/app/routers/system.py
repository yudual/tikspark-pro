from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..schemas import SystemSettingsResponse, SystemSettingsUpdateRequest
from ..services.app_settings_service import (
    get_admin_token,
    get_default_schedule_window,
    get_dispatch_jitter_max,
    get_dispatch_jitter_min,
    get_scheduler_scan_interval,
    get_webhook_url,
    is_auto_schedule_enabled,
    is_manual_review_mode,
    set_setting_bool,
    set_setting_int,
    set_setting_str,
)

router = APIRouter(prefix="/system", tags=["system"])


def _build_system_settings_response(db: Session) -> SystemSettingsResponse:
    settings = get_settings()
    admin_token = get_admin_token(db)
    return SystemSettingsResponse(
        app_name=settings.app_name,
        api_prefix=settings.api_prefix,
        admin_token_configured=bool(admin_token),
        scheduler_enabled=is_auto_schedule_enabled(db),
        scheduler_scan_interval_seconds=get_scheduler_scan_interval(db),
        dispatch_jitter_min_seconds=get_dispatch_jitter_min(db),
        dispatch_jitter_max_seconds=get_dispatch_jitter_max(db),
        manual_review_mode=is_manual_review_mode(db),
        webhook_url=get_webhook_url(db),
        sqlite_path=settings.sqlite_path,
        secret_key_path=settings.secret_key_path,
        cors_origins=list(settings.cors_origins),
        default_schedule_window=get_default_schedule_window(db),
    )


@router.get("/settings", response_model=SystemSettingsResponse)
def get_system_settings(db: Session = Depends(get_db)) -> SystemSettingsResponse:
    return _build_system_settings_response(db)


@router.patch("/settings", response_model=SystemSettingsResponse)
def update_system_settings(
    payload: SystemSettingsUpdateRequest, db: Session = Depends(get_db)
) -> SystemSettingsResponse:
    if payload.default_schedule_window is not None:
        set_setting_str(db, "default_schedule_window", payload.default_schedule_window.strip())
    if payload.scheduler_scan_interval_seconds is not None:
        set_setting_int(db, "scheduler_scan_interval_seconds", payload.scheduler_scan_interval_seconds)
    if payload.dispatch_jitter_min_seconds is not None:
        set_setting_int(db, "dispatch_jitter_min_seconds", payload.dispatch_jitter_min_seconds)
    if payload.dispatch_jitter_max_seconds is not None:
        set_setting_int(db, "dispatch_jitter_max_seconds", payload.dispatch_jitter_max_seconds)
    if payload.manual_review_mode is not None:
        set_setting_bool(db, "manual_review_mode", payload.manual_review_mode)
    if payload.webhook_url is not None:
        set_setting_str(db, "webhook_url", payload.webhook_url.strip())
    if payload.admin_token is not None:
        set_setting_str(db, "admin_token", payload.admin_token.strip())

    db.commit()
    return _build_system_settings_response(db)
