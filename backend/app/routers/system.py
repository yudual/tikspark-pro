from fastapi import APIRouter

from ..config import get_settings
from ..schemas import SystemSettingsResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/settings", response_model=SystemSettingsResponse)
def get_system_settings() -> SystemSettingsResponse:
    settings = get_settings()
    return SystemSettingsResponse(
        app_name=settings.app_name,
        api_prefix=settings.api_prefix,
        admin_token_configured=bool(settings.admin_token),
        scheduler_enabled=settings.scheduler_enabled,
        scheduler_scan_interval_seconds=settings.scheduler_scan_interval_seconds,
        manual_review_mode=settings.manual_review_mode,
        sqlite_path=settings.sqlite_path,
        secret_key_path=settings.secret_key_path,
        cors_origins=list(settings.cors_origins),
        default_schedule_window=settings.default_schedule_window,
    )
