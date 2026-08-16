from fastapi import Depends, HTTPException, Request, status

from .config import get_settings


def require_admin_token(request: Request) -> None:
    settings = get_settings()
    if not settings.admin_token:
        return

    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {settings.admin_token}"
    if authorization == expected:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="需要管理员访问令牌。",
        headers={"WWW-Authenticate": "Bearer"},
    )


AdminRequired = Depends(require_admin_token)
