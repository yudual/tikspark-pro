from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..database import SessionLocal, get_db
from ..models import Account, AccountStatus, DispatchSource, DispatchTask, Friend, Message, RunLog, RunStatus
from ..schemas import (
    AutoScheduleBatchStrategyUpdateRequest,
    AutoScheduleItem,
    AutoScheduleRegenerateRequest,
    AutoScheduleSettingsUpdateRequest,
    AutoScheduleSummary,
    DashboardSummary,
    DispatchTaskResponse,
    PaginatedLogsResponse,
    PaginatedTasksResponse,
    RunLogResponse,
    SchedulePreviewDay,
    SchedulePreviewOccurrence,
    SchedulePreviewResponse,
    SystemStatusResponse,
)
from ..services.app_settings_service import is_auto_schedule_enabled, set_auto_schedule_enabled
from ..services.dispatch_service import dispatch_active_messages, is_dispatch_running_in_db
from ..services.schedule_service import (
    compute_friend_next_run_at,
    get_local_now,
    normalize_schedule_window,
    sanitize_cooldown_minutes,
    sanitize_frequency_days,
    sanitize_retry_cooldown_minutes,
    sanitize_retry_limit,
    validate_schedule_window,
)
from ..state import global_state
from ..text_utils import repair_mojibake

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _build_schedule_status(
    friend: Friend,
    latest_log: RunLog | None,
    *,
    now,
    enabled: bool,
) -> tuple[str, str, str]:
    is_current_target = (
        global_state.current_friend == friend.friend_nickname
        and global_state.current_account == friend.account.nickname
    )

    if not enabled:
        return ("paused", "已暂停", "自动续火花总开关已关闭，当前不会自动扫描或入队。")

    if is_current_target:
        if global_state.mode == "sending":
            return ("sending", "发送中", global_state.status_text or "浏览器正在执行自动发送。")
        if global_state.mode == "jitter_wait":
            return ("jitter_wait", "错峰等待", global_state.status_text or "正在执行随机错峰等待。")
        if global_state.mode == "manual_review":
            return ("manual_review", "人工复核", global_state.status_text or "本次任务已进入人工复核队列。")
        if global_state.mode in {"dispatching", "scanning"}:
            return ("queued", "已入队", global_state.current_step or "任务已进入自动执行队列。")

    if friend.next_run_at is None:
        return ("unscheduled", "待生成计划", "当前还没有随机执行时间，开启后将在下一轮扫描时生成计划。")

    if friend.next_run_at <= now:
        return ("queued", "已到点待执行", "已经到达执行时间，等待调度引擎扫描并放入执行队列。")

    if latest_log and latest_log.status == RunStatus.failed and friend.consecutive_failures > 0:
        remaining = max(friend.retry_limit - friend.consecutive_failures, 0)
        return (
            "retry_wait",
            "等待重试",
            f"上次发送失败，系统将在 {friend.retry_cooldown_minutes} 分钟后再次尝试，剩余 {remaining} 次自动重试。",
        )

    if latest_log and latest_log.status == RunStatus.manual_review:
        return ("manual_review", "待人工复核", "上次到点任务进入人工复核队列，尚未真正自动发送。")

    return ("waiting_scan", "待扫描", "当前计划正常，系统会在下次扫描时检查是否到点。")


def _default_last_result_summary(latest_log: RunLog | None) -> tuple[str, str, object | None]:
    if latest_log is None:
        return ("", "", None)
    return (
        repair_mojibake(latest_log.summary),
        repair_mojibake(latest_log.details),
        latest_log.created_at,
    )


def _serialize_run_log(log: RunLog) -> RunLogResponse:
    return RunLogResponse(
        id=log.id,
        friend_id=log.friend_id,
        status=log.status,
        summary=repair_mojibake(log.summary),
        details=repair_mojibake(log.details),
        created_at=log.created_at,
    )


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


def _build_schedule_preview_occurrences(friend: Friend, *, now, horizon_end) -> list[SchedulePreviewOccurrence]:
    occurrences: list[SchedulePreviewOccurrence] = []
    last_run_at = friend.last_run_at
    cursor = friend.next_run_at
    if cursor is None:
        cursor = compute_friend_next_run_at(
            schedule_window=friend.schedule_window,
            now=now,
            frequency_days=friend.frequency_days,
            cooldown_minutes=friend.cooldown_minutes,
            last_run_at=last_run_at,
        )

    while cursor <= horizon_end:
        occurrences.append(
            SchedulePreviewOccurrence(
                friend_id=friend.id,
                account_id=friend.account_id,
                account_name=repair_mojibake(friend.account.nickname),
                friend_name=repair_mojibake(friend.friend_nickname),
                planned_at=cursor,
                schedule_window=friend.schedule_window,
                frequency_days=friend.frequency_days,
                message_type=friend.message.message_type if friend.message else None,
            )
        )
        last_run_at = cursor
        cursor = compute_friend_next_run_at(
            schedule_window=friend.schedule_window,
            now=cursor,
            frequency_days=friend.frequency_days,
            cooldown_minutes=friend.cooldown_minutes,
            last_run_at=last_run_at,
        )
    return occurrences


def _serialize_auto_schedule_item(
    friend: Friend,
    latest_log: RunLog | None,
    *,
    now,
    enabled: bool,
) -> AutoScheduleItem:
    current_status, current_status_label, current_status_reason = _build_schedule_status(
        friend,
        latest_log,
        now=now,
        enabled=enabled,
    )
    last_summary, last_details, last_created_at = _default_last_result_summary(latest_log)
    return AutoScheduleItem(
        friend_id=friend.id,
        account_id=friend.account_id,
        account_name=repair_mojibake(friend.account.nickname),
        friend_name=repair_mojibake(friend.friend_nickname),
        friend_avatar=friend.friend_avatar,
        schedule_window=friend.schedule_window,
        frequency_days=friend.frequency_days,
        cooldown_minutes=friend.cooldown_minutes,
        retry_limit=friend.retry_limit,
        retry_cooldown_minutes=friend.retry_cooldown_minutes,
        consecutive_failures=friend.consecutive_failures,
        next_run_at=friend.next_run_at,
        last_run_at=friend.last_run_at,
        message_type=friend.message.message_type if friend.message else None,
        current_status=current_status,
        current_status_label=current_status_label,
        current_status_reason=current_status_reason,
        last_result_status=latest_log.status if latest_log else None,
        last_result_summary=last_summary,
        last_result_details=last_details,
        last_result_at=last_created_at,
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


@router.get("/system-status", response_model=SystemStatusResponse)
def get_system_status(db: Session = Depends(get_db)) -> SystemStatusResponse:
    latest_success = db.execute(
        select(RunLog).where(RunLog.status == RunStatus.success).order_by(RunLog.created_at.desc()).limit(1)
    ).scalars().first()
    latest_failure = db.execute(
        select(RunLog).where(RunLog.status == RunStatus.failed).order_by(RunLog.created_at.desc()).limit(1)
    ).scalars().first()
    retry_candidates = (
        db.execute(
            select(Friend.retry_limit, Friend.consecutive_failures)
            .where(Friend.is_active.is_(True), Friend.consecutive_failures > 0)
        )
        .all()
    )
    retry_remaining = global_state.retry_remaining
    if retry_remaining <= 0 and retry_candidates:
        retry_remaining = max(max(limit - failures, 0) for limit, failures in retry_candidates)

    return SystemStatusResponse(
        is_running=global_state.is_running,
        total_tasks=global_state.total_tasks,
        completed_tasks=global_state.completed_tasks,
        status_text=repair_mojibake(global_state.status_text),
        mode=global_state.mode,
        current_account=repair_mojibake(global_state.current_account),
        current_friend=repair_mojibake(global_state.current_friend),
        current_step=repair_mojibake(global_state.current_step),
        last_scan_at=global_state.last_scan_at,
        next_scan_at=global_state.next_scan_at,
        due_task_total=global_state.due_task_total,
        queued_task_total=global_state.queued_task_total,
        last_error=repair_mojibake(global_state.last_error),
        scan_started_at=global_state.scan_started_at,
        last_scan_duration_ms=global_state.last_scan_duration_ms,
        current_wait_seconds=global_state.current_wait_seconds,
        last_success_at=global_state.last_success_at or (latest_success.created_at if latest_success else None),
        last_success_summary=repair_mojibake(global_state.last_success_summary or (latest_success.summary if latest_success else "")),
        last_success_target=repair_mojibake(global_state.last_success_target),
        last_failure_at=global_state.last_failure_at or (latest_failure.created_at if latest_failure else None),
        last_failure_reason=repair_mojibake(global_state.last_failure_reason or (latest_failure.details if latest_failure else "")),
        retry_remaining=retry_remaining,
        blocked_point=repair_mojibake(global_state.blocked_point),
    )


@router.post("/run-tasks")
def run_all_tasks(
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


@router.get("/auto-schedule", response_model=AutoScheduleSummary)
def get_auto_schedule(db: Session = Depends(get_db)) -> AutoScheduleSummary:
    settings = get_settings()
    now = get_local_now()
    enabled = is_auto_schedule_enabled(db)
    friends = (
        db.execute(
            select(Friend)
            .options(joinedload(Friend.account), joinedload(Friend.message))
            .where(Friend.is_active.is_(True))
            .order_by(Friend.next_run_at.is_(None), Friend.next_run_at.asc())
        )
        .scalars()
        .all()
    )
    overdue_total = sum(
        1 for friend in friends if friend.next_run_at is not None and friend.next_run_at <= now
    )
    next_run_at = min(
        (friend.next_run_at for friend in friends if friend.next_run_at is not None),
        default=None,
    )

    latest_logs_by_friend: dict[int, RunLog] = {}
    friend_ids = [friend.id for friend in friends]
    if friend_ids:
        logs = (
            db.execute(
                select(RunLog)
                .where(RunLog.friend_id.in_(friend_ids))
                .order_by(RunLog.created_at.desc())
            )
            .scalars()
            .all()
        )
        for log in logs:
            latest_logs_by_friend.setdefault(log.friend_id, log)

    items = [
        _serialize_auto_schedule_item(friend, latest_logs_by_friend.get(friend.id), now=now, enabled=enabled)
        for friend in friends[:8]
    ]

    return AutoScheduleSummary(
        enabled=enabled,
        scan_interval_seconds=settings.scheduler_scan_interval_seconds,
        active_total=len(friends),
        scheduled_total=sum(1 for friend in friends if friend.next_run_at is not None),
        overdue_total=overdue_total,
        next_run_at=next_run_at,
        items=items,
    )


@router.get("/auto-schedule/preview", response_model=SchedulePreviewResponse)
def get_auto_schedule_preview(
    days: int = 7,
    account_id: int | None = None,
    db: Session = Depends(get_db),
) -> SchedulePreviewResponse:
    days = min(max(days, 1), 14)
    now = get_local_now()
    horizon_end = now + timedelta(days=days)
    query = (
        select(Friend)
        .options(joinedload(Friend.account), joinedload(Friend.message))
        .where(Friend.is_active.is_(True))
    )
    if account_id is not None:
        query = query.where(Friend.account_id == account_id)
    friends = (
        db.execute(query)
        .scalars()
        .all()
    )

    occurrences: list[SchedulePreviewOccurrence] = []
    for friend in friends:
        friend.schedule_window = normalize_schedule_window(friend.schedule_window)
        occurrences.extend(_build_schedule_preview_occurrences(friend, now=now, horizon_end=horizon_end))

    occurrences.sort(key=lambda item: item.planned_at)
    days_map: dict[str, list[SchedulePreviewOccurrence]] = {}
    for item in occurrences:
        days_map.setdefault(item.planned_at.date().isoformat(), []).append(item)

    items = [
        SchedulePreviewDay(
            date=date,
            label=date,
            total=len(day_items),
            items=day_items,
        )
        for date, day_items in sorted(days_map.items())
    ]
    return SchedulePreviewResponse(days=days, total=len(occurrences), items=items)


@router.patch("/auto-schedule/settings", response_model=AutoScheduleSummary)
def update_auto_schedule_settings(
    payload: AutoScheduleSettingsUpdateRequest,
    db: Session = Depends(get_db),
) -> AutoScheduleSummary:
    set_auto_schedule_enabled(db, payload.enabled)
    return get_auto_schedule(db)


@router.post("/auto-schedule/regenerate", response_model=AutoScheduleSummary)
def regenerate_auto_schedule(
    payload: AutoScheduleRegenerateRequest,
    db: Session = Depends(get_db),
) -> AutoScheduleSummary:
    now = get_local_now()
    query = select(Friend).where(Friend.is_active.is_(True))
    if payload.account_id is not None:
        query = query.where(Friend.account_id == payload.account_id)

    friends = db.execute(query).scalars().all()
    for friend in friends:
        friend.schedule_window = normalize_schedule_window(friend.schedule_window)
        if payload.only_overdue and friend.next_run_at is not None and friend.next_run_at > now:
            continue
        friend.next_run_at = compute_friend_next_run_at(
            schedule_window=friend.schedule_window,
            now=now,
            frequency_days=friend.frequency_days,
            cooldown_minutes=friend.cooldown_minutes,
            last_run_at=friend.last_run_at,
        )
        friend.consecutive_failures = 0

    db.commit()
    return get_auto_schedule(db)


@router.patch("/auto-schedule/batch-strategy", response_model=AutoScheduleSummary)
def update_auto_schedule_batch_strategy(
    payload: AutoScheduleBatchStrategyUpdateRequest,
    db: Session = Depends(get_db),
) -> AutoScheduleSummary:
    try:
        schedule_window = validate_schedule_window(payload.schedule_window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    frequency_days = sanitize_frequency_days(payload.frequency_days)
    cooldown_minutes = sanitize_cooldown_minutes(payload.cooldown_minutes)
    retry_limit = sanitize_retry_limit(payload.retry_limit)
    retry_cooldown_minutes = sanitize_retry_cooldown_minutes(payload.retry_cooldown_minutes)
    now = get_local_now()

    query = select(Friend).where(Friend.is_active.is_(True))
    if payload.account_id is not None:
        query = query.where(Friend.account_id == payload.account_id)

    friends = db.execute(query).scalars().all()
    for friend in friends:
        friend.schedule_window = schedule_window
        friend.frequency_days = frequency_days
        friend.cooldown_minutes = cooldown_minutes
        friend.retry_limit = retry_limit
        friend.retry_cooldown_minutes = retry_cooldown_minutes
        friend.next_run_at = compute_friend_next_run_at(
            schedule_window=friend.schedule_window,
            now=now,
            frequency_days=friend.frequency_days,
            cooldown_minutes=friend.cooldown_minutes,
            last_run_at=friend.last_run_at,
        )

    db.commit()
    return get_auto_schedule(db)


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummary:
    account_total = db.scalar(select(func.count(Account.id))) or 0
    healthy_account_total = db.scalar(
        select(func.count(Account.id)).where(Account.status == AccountStatus.healthy)
    ) or 0
    invalid_account_total = db.scalar(
        select(func.count(Account.id)).where(Account.status == AccountStatus.invalid)
    ) or 0
    active_friend_total = db.scalar(
        select(func.count(Friend.id)).where(Friend.is_active.is_(True))
    ) or 0
    configured_message_total = db.scalar(select(func.count(Message.id))) or 0
    manual_review_job_total = db.scalar(
        select(func.count(RunLog.id)).where(RunLog.status == RunStatus.manual_review)
    ) or 0
    latest_logs = (
        db.execute(select(RunLog).order_by(RunLog.created_at.desc()).limit(8)).scalars().all()
    )

    return DashboardSummary(
        account_total=account_total,
        healthy_account_total=healthy_account_total,
        invalid_account_total=invalid_account_total,
        active_friend_total=active_friend_total,
        configured_message_total=configured_message_total,
        manual_review_job_total=manual_review_job_total,
        latest_logs=[_serialize_run_log(log) for log in latest_logs],
    )


@router.get("/logs", response_model=PaginatedLogsResponse)
def list_logs(
    page: int = 1,
    limit: int = 50,
    account_id: int | None = None,
    db: Session = Depends(get_db),
) -> PaginatedLogsResponse:
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    query = select(RunLog).join(RunLog.friend)

    if account_id:
        query = query.where(Friend.account_id == account_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    logs = (
        db.execute(
            query.order_by(RunLog.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return PaginatedLogsResponse(
        items=[_serialize_run_log(log) for log in logs],
        total=total,
    )


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
