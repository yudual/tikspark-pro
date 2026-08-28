from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import Friend
from .app_settings_service import is_auto_schedule_enabled
from .dispatch_service import dispatch_active_messages
from .schedule_service import compute_friend_next_run_at, get_local_now, normalize_schedule_window
from ..state import global_state


def run_dispatch_scan(db: Session) -> None:
    """一次完整调度扫描：刷新状态、生成缺失计划、派发到点好友。

    独立成函数以便集成测试直接调用；APScheduler 任务只是它的定时外壳。
    """
    now = get_local_now()
    settings = get_settings()
    global_state.scan_started_at = now
    auto_schedule_enabled = is_auto_schedule_enabled(db)
    global_state.mode = "scanning"
    global_state.current_step = "正在扫描自动续火计划"
    global_state.status_text = "自动续火扫描中"
    global_state.last_scan_at = now
    global_state.next_scan_at = now + timedelta(seconds=settings.scheduler_scan_interval_seconds)
    global_state.current_wait_seconds = 0
    global_state.retry_remaining = 0
    global_state.blocked_point = ""
    active_friends = (
        db.execute(select(Friend).where(Friend.is_active.is_(True))).scalars().all()
    )

    global_state.queued_task_total = len(active_friends)

    if not auto_schedule_enabled:
        global_state.mode = "idle"
        global_state.current_step = "自动扫描已暂停，等待重新开启"
        global_state.status_text = "自动续火计划已关闭"
        global_state.due_task_total = 0
        global_state.current_account = ""
        global_state.current_friend = ""
        global_state.last_error = ""
        global_state.blocked_point = "自动续火总开关已关闭"
        return

    due_friend_ids: list[int] = []
    for friend in active_friends:
        friend.schedule_window = normalize_schedule_window(friend.schedule_window)
        if friend.next_run_at is None:
            friend.next_run_at = compute_friend_next_run_at(
                schedule_window=friend.schedule_window,
                now=now,
                frequency_days=friend.frequency_days,
                cooldown_minutes=friend.cooldown_minutes,
                last_run_at=friend.last_run_at,
            )
        elif friend.next_run_at <= now:
            due_friend_ids.append(friend.id)

    db.commit()
    global_state.due_task_total = len(due_friend_ids)

    if due_friend_ids:
        global_state.mode = "dispatching"
        global_state.current_step = f"发现 {len(due_friend_ids)} 个到点任务，正在交给执行队列"
        global_state.blocked_point = ""
        dispatch_active_messages(db, friend_ids=due_friend_ids, is_auto_cron=True)
    else:
        global_state.mode = "idle"
        global_state.current_step = "没有到点任务，等待下一次自动扫描"
        global_state.status_text = "系统空闲中，自动续火计划已开启"
        global_state.current_account = ""
        global_state.current_friend = ""
        global_state.last_error = ""
        global_state.blocked_point = "当前没有到点任务"


def build_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    timezone = ZoneInfo("Asia/Shanghai")
    scheduler = BackgroundScheduler(timezone=timezone)

    def run_dispatch_job() -> None:
        db = SessionLocal()
        try:
            run_dispatch_scan(db)
        except Exception as exc:
            global_state.mode = "error"
            global_state.current_step = "自动扫描异常"
            global_state.last_error = str(exc)
            global_state.blocked_point = "扫描阶段异常"
            raise
        finally:
            finished_at = get_local_now()
            if global_state.scan_started_at is not None:
                global_state.last_scan_duration_ms = max(
                    0,
                    int((finished_at - global_state.scan_started_at).total_seconds() * 1000),
                )
            db.close()

    if settings.scheduler_enabled:
        scheduler.add_job(
            run_dispatch_job,
            IntervalTrigger(
                seconds=settings.scheduler_scan_interval_seconds,
                timezone=timezone,
            ),
            id="dispatch-due-friends",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone),
        )
    return scheduler

