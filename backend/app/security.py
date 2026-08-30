from .config import get_settings
from .database import SessionLocal
from .models import AppSetting


def require_admin_token(request: Request) -> None:
    db = SessionLocal()
    try:
        setting = db.get(AppSetting, "admin_token")
        active_token = setting.value if (setting and setting.value) else get_settings().admin_token
    finally:
        db.close()

    if not active_token:
        return

    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {active_token}"
    if authorization == expected:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="需要管理员访问令牌。",
        headers={"WWW-Authenticate": "Bearer"},
    )


AdminRequired = Depends(require_admin_token)
