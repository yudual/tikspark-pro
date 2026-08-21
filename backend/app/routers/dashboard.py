from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, AccountStatus, Friend, Message, RunLog, RunStatus
from ..schemas import DashboardSummary, RunLogResponse, SystemStatusResponse
from ..state import global_state
from ..text_utils import repair_mojibake

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _serialize_run_log(log: RunLog) -> RunLogResponse:
    return RunLogResponse(
        id=log.id,
        friend_id=log.friend_id,
        status=log.status,
        summary=repair_mojibake(log.summary),
        details=repair_mojibake(log.details),
        created_at=log.created_at,
    )


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
    failed_friend_total = db.scalar(
        select(func.count(Friend.id)).where(Friend.is_active.is_(True), Friend.consecutive_failures > 0)
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
        failed_friend_total=failed_friend_total,
        latest_logs=[_serialize_run_log(log) for log in latest_logs],
    )
