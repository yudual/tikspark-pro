import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import get_settings
from .database import Base, engine, ensure_sqlite_schema
from .routers import accounts, dashboard, messages
from .services.scheduler import build_scheduler

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


settings = get_settings()
scheduler = build_scheduler() if settings.scheduler_enabled else None
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema()
    if scheduler is not None and not scheduler.running:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_api_routes(request: Request, call_next):
    if settings.admin_token and request.url.path.startswith(settings.api_prefix):
        expected = f"Bearer {settings.admin_token}"
        if request.headers.get("authorization", "") != expected:
            return JSONResponse(
                status_code=401,
                content={"detail": "需要管理员访问令牌。"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@app.get("/health")
def healthcheck() -> dict[str, str | bool]:
    return {"status": "ok", "auth_required": bool(settings.admin_token)}


app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(accounts.router, prefix=settings.api_prefix)
app.include_router(messages.router, prefix=settings.api_prefix)


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    api_prefix = settings.api_prefix.strip("/")
    if full_path == api_prefix or full_path.startswith(api_prefix + "/"):
        raise HTTPException(status_code=404, detail="API route not found")
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    requested_path = (FRONTEND_DIST / full_path).resolve()
    try:
        requested_path.relative_to(FRONTEND_DIST.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    if requested_path.is_file():
        return FileResponse(requested_path)
    return FileResponse(FRONTEND_INDEX)
