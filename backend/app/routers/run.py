from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import SessionLocal, get_db
from ..models import DispatchSource, DispatchTask, Friend, RunStatus
from ..schemas import DispatchTaskResponse, PaginatedTasksResponse
from ..services.dispatch_service import dispatch_active_messages, is_dispatch_running_in_db
from ..text_utils import repair_mojibake

router = APIRouter(prefix="/run", tags=["run"])


def _serialize_dispatch_task(task: DispatchTask) -> DispatchTaskResponse:
    return DispatchTaskResponse(
        id=task.id,
        friend_id=task.friend_id,
        account_id=task.friend.account_id,
        account_name=repair_mojibake(task.friend.account.nickname),
        friend_name=repair_mojibake(task.friend.friend_nickname),
        source=task.source,
        status=task.status,
        idempotency_key=task.idempotency_key,
        scheduled_for=task.scheduled_for,
        started_at=task.started_at,
        finished_at=task.finished_at,
        summary=repair_mojibake(task.summary),
        details=repair_mojibake(task.details),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _run_tasks_background(account_id: int | None = None, friend_id: int | None = None, is_auto_cron: bool = False):
    db = SessionLocal()
    try:
        dispatch_active_messages(
            db,
            account_id=account_id,
            friend_id=friend_id,
            is_auto_cron=is_auto_cron,
        )
    finally:
        db.close()


@router.post("/tasks")
def run_tasks(
    background_tasks: BackgroundTasks,
    account_id: int | None = None,
    friend_id: int | None = None,
    is_auto_cron: bool = False,
    db: Session = Depends(get_db),
):
    if is_dispatch_running_in_db(db):
        raise HTTPException(status_code=409, detail="任务调度正在运行。")
    background_tasks.add_task(_run_tasks_background, account_id, friend_id, is_auto_cron)
    return {"message": "任务调度已在后台启动。"}


@router.get("/tasks", response_model=PaginatedTasksResponse)
def list_dispatch_tasks(
    page: int = 1,
    limit: int = 50,
    account_id: int | None = None,
    status: RunStatus | None = None,
    source: DispatchSource | None = None,
    db: Session = Depends(get_db),
) -> PaginatedTasksResponse:
    page = max(page, 1)
    limit = min(max(limit, 1), 100)

    query = (
        select(DispatchTask)
        .join(DispatchTask.friend)
        .options(joinedload(DispatchTask.friend).joinedload(Friend.account))
    )

    if account_id:
        query = query.where(Friend.account_id == account_id)
    if status:
        query = query.where(DispatchTask.status == status)
    if source:
        query = query.where(DispatchTask.source == source)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    tasks = (
        db.execute(
            query.order_by(DispatchTask.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return PaginatedTasksResponse(
        items=[_serialize_dispatch_task(task) for task in tasks],
        total=total,
    )
