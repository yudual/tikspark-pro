from __future__ import annotations

import random
import time
from datetime import datetime
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import (
    AccountStatus,
    DispatchSource,
    DispatchTask,
    Friend,
    MessageType,
    RunLog,
    RunStatus,
)
from ..state import global_state
from .dispatch_task_service import (
    acquire_dispatch_lock,
    create_dispatch_task,
    is_dispatch_locked,
    mark_task_finished,
    mark_task_running,
    release_dispatch_lock,
)
from .execution_service import SPARK_STICKER_TOKEN, execution_service
from .schedule_service import (
    compute_friend_next_run_at,
    compute_retry_run_at,
    get_local_now,
    normalize_schedule_window,
)
from .secret_service import get_secret_service

_dispatch_lock = Lock()


def is_dispatch_running() -> bool:
    return _dispatch_lock.locked()


def is_dispatch_running_in_db(db: Session) -> bool:
    return is_dispatch_running() or is_dispatch_locked(db)


def retry_failed_tasks(db: Session) -> int:
    """一键重试所有失败/需重试的好友任务。"""
    failed_friends = (
        db.execute(
            select(Friend)
            .options(joinedload(Friend.account), joinedload(Friend.message))
            .where(Friend.is_active.is_(True), Friend.consecutive_failures > 0)
        )
        .scalars()
        .all()
    )
    if not failed_friends:
        # 查找最新日志为失败的好友
        subq = (
            select(RunLog.friend_id)
            .where(RunLog.status == RunStatus.failed)
            .order_by(RunLog.created_at.desc())
            .limit(50)
        )
        failed_friends = (
            db.execute(
                select(Friend)
                .options(joinedload(Friend.account), joinedload(Friend.message))
                .where(Friend.is_active.is_(True), Friend.id.in_(subq))
            )
            .scalars()
            .all()
        )
    if not failed_friends:
        return 0
    friend_ids = [f.id for f in failed_friends]
    return dispatch_active_messages(db, friend_ids=friend_ids, is_auto_cron=False)


def dispatch_active_messages(
    db: Session,
    account_id: int | None = None,
    friend_id: int | None = None,
    friend_ids: list[int] | None = None,
    is_auto_cron: bool = False,
) -> int:
    """Dispatch active friends immediately or through the automatic queue."""
    if not _dispatch_lock.acquire(blocking=False):
        _mark_dispatch_skipped("已有任务正在运行，本次触发已跳过。")
        return 0

    db_lock = acquire_dispatch_lock(db)
    if db_lock is None:
        if _dispatch_lock.locked():
            _dispatch_lock.release()
        _mark_dispatch_skipped("已有任务正在运行，本次触发已跳过。")
        return 0

    global_state.is_running = True
    global_state.mode = "dispatching"
    global_state.current_step = "正在初始化执行队列"
    global_state.status_text = "正在初始化调度队列..."
    global_state.current_account = ""
    global_state.current_friend = ""
    global_state.last_error = ""
    global_state.current_wait_seconds = 0
    global_state.retry_remaining = 0
    global_state.blocked_point = ""

    try:
        from .app_settings_service import get_setting_str
        settings = get_settings()
        db_manual_review = get_setting_str(db, "manual_review_mode", "")
        manual_review = (
            (db_manual_review.lower() in {"1", "true", "yes", "on"})
            if db_manual_review
            else settings.manual_review_mode
        )
        db_jitter_min = get_setting_str(db, "dispatch_jitter_min_seconds", "")
        jitter_min = int(db_jitter_min) if db_jitter_min.isdigit() else settings.dispatch_jitter_min_seconds
        db_jitter_max = get_setting_str(db, "dispatch_jitter_max_seconds", "")
        jitter_max = int(db_jitter_max) if db_jitter_max.isdigit() else settings.dispatch_jitter_max_seconds
        current_time = get_local_now()
        active_friends = _load_active_friends(
            db,
            account_id=account_id,
            friend_id=friend_id,
            friend_ids=friend_ids,
        )
        random.shuffle(active_friends)

        source = DispatchSource.auto if is_auto_cron else DispatchSource.manual
        tasks_by_friend_id = _create_tasks_for_friends(db, active_friends, source=source)

        global_state.total_tasks = len(active_friends)
        global_state.completed_tasks = 0

        if not active_friends:
            global_state.status_text = "当前没有待执行的自动续火花任务"
            global_state.mode = "idle"
            global_state.current_step = "没有可执行任务"
            global_state.blocked_point = "自动续火花池为空"
            return 0

        created_logs = 0
        for index, friend in enumerate(active_friends):
            task = tasks_by_friend_id.get(friend.id)
            if is_auto_cron and not manual_review and index > 0:
                _wait_between_auto_tasks(
                    jitter_min,
                    jitter_max,
                )

            _mark_current_friend(friend)
            if task:
                mark_task_running(task)
            db.commit()

            try:
                result_status, summary, details = _run_friend_task(
                    db,
                    friend,
                    current_time=current_time,
                    manual_review_mode=manual_review,
                )
            except Exception as task_exc:
                result_status = RunStatus.failed
                summary = "执行异常"
                details = f"任务处理异常: {task_exc}"
                db.add(
                    RunLog(
                        friend_id=friend.id,
                        status=result_status,
                        summary=summary,
                        details=details,
                        created_at=get_local_now(),
                    )
                )

            if task:
                mark_task_finished(task, result_status, summary, details)
            _mark_friend_run(friend, current_time, result_status)
            global_state.retry_remaining = (
                max(friend.retry_limit - friend.consecutive_failures, 0)
                if result_status == RunStatus.failed
                else 0
            )
            created_logs += 1
            global_state.completed_tasks += 1
            db.commit()

        db.commit()
        return created_logs
    finally:
        _reset_dispatch_state()
        release_dispatch_lock(db, db_lock)
        if _dispatch_lock.locked():
            _dispatch_lock.release()


def _load_active_friends(
    db: Session,
    *,
    account_id: int | None,
    friend_id: int | None,
    friend_ids: list[int] | None,
) -> list[Friend]:
    query = (
        select(Friend)
        .options(joinedload(Friend.account), joinedload(Friend.message))
        .where(Friend.is_active.is_(True))
    )
    if account_id:
        query = query.where(Friend.account_id == account_id)
    if friend_id:
        query = query.where(Friend.id == friend_id)
    if friend_ids:
        query = query.where(Friend.id.in_(friend_ids))
    return list(db.execute(query).scalars().all())


def _create_tasks_for_friends(
    db: Session,
    friends: list[Friend],
    *,
    source: DispatchSource,
) -> dict[int, DispatchTask]:
    tasks: dict[int, DispatchTask] = {}
    for friend in friends:
        tasks[friend.id] = create_dispatch_task(
            db,
            friend,
            source=source,
            scheduled_for=friend.next_run_at if source == DispatchSource.auto else None,
        )
    db.commit()
    return tasks


def _wait_between_auto_tasks(min_seconds: int, max_seconds: int) -> None:
    jitter_seconds = random.randint(max(1, min_seconds), max(min_seconds, max_seconds))
    for remaining in range(jitter_seconds, 0, -1):
        global_state.mode = "jitter_wait"
        global_state.current_step = "错峰等待"
        global_state.status_text = f"错峰等待中：{remaining} 秒后继续..."
        global_state.current_wait_seconds = remaining
        global_state.blocked_point = "正在执行错峰等待"
        time.sleep(1)


def _mark_current_friend(friend: Friend) -> None:
    global_state.mode = "sending"
    global_state.current_account = friend.account.nickname
    global_state.current_friend = friend.friend_nickname
    global_state.current_step = "正在定位好友并发送续火花消息"
    global_state.status_text = f"正在执行：{friend.account.nickname} -> {friend.friend_nickname}"
    global_state.current_wait_seconds = 0
    global_state.blocked_point = ""


def _run_friend_task(
    db: Session,
    friend: Friend,
    *,
    current_time: datetime,
    manual_review_mode: bool,
) -> tuple[RunStatus, str, str]:
    if friend.account.status == AccountStatus.invalid:
        summary = "账号凭证失效"
        details = "账号状态已标记为失效，请先在【账号管理】页面更新该账号的 Cookie 凭证。"
        global_state.current_step = "账号凭证失效，跳过本次任务"
        global_state.last_failure_at = current_time
        global_state.last_failure_reason = details
        global_state.blocked_point = "账号凭证失效"
        db.add(RunLog(friend_id=friend.id, status=RunStatus.failed, summary=summary, details=details, created_at=get_local_now()))
        return RunStatus.failed, summary, details

    content = _resolve_message_content(friend)
    if manual_review_mode:
        summary = "已加入人工复核队列"
        details = f"账号={friend.account.nickname} 好友={friend.friend_nickname} 内容={content}"
        global_state.mode = "manual_review"
        global_state.current_step = "人工复核模式，写入复核队列"
        global_state.blocked_point = "人工复核模式阻止自动外发"
        db.add(RunLog(friend_id=friend.id, status=RunStatus.manual_review, summary=summary, details=details, created_at=get_local_now()))
        return RunStatus.manual_review, summary, details

    global_state.current_step = "浏览器自动化发送中"
    result = execution_service.send_message(friend.account, friend, content)
    result_status = RunStatus.success if result.success else RunStatus.failed

    refreshed_cookies = getattr(result, "refreshed_cookies", None)
    if result.success and refreshed_cookies and "sessionid" in refreshed_cookies:
        try:
            friend.account.cookie_text = get_secret_service().encrypt(refreshed_cookies)
            friend.account.cookie_updated_at = current_time
            if friend.account.status != AccountStatus.healthy:
                friend.account.status = AccountStatus.healthy
                friend.account.status_reason = "会话活跃且已自动刷新凭证"
        except Exception:
            pass

    if result.summary in ("账号凭证已失效", "凭证失效"):
        friend.account.status = AccountStatus.invalid
        friend.account.status_reason = result.details
    elif result.summary == "页面被风控拦截":
        friend.account.status_reason = f"风控提示: {result.details}"

    if result.success:
        global_state.last_success_at = current_time
        global_state.last_success_summary = result.summary
        global_state.last_success_target = f"{friend.account.nickname} -> {friend.friend_nickname}"
        global_state.blocked_point = ""
    else:
        global_state.last_error = result.details
        global_state.last_failure_at = current_time
        global_state.last_failure_reason = result.details
        global_state.blocked_point = "发送阶段未通过"

    db.add(
        RunLog(
            friend_id=friend.id,
            status=result_status,
            summary=result.summary,
            details=result.details,
            created_at=get_local_now(),
        )
    )
    return result_status, result.summary, result.details


def _resolve_message_content(friend: Friend) -> str:
    content = friend.message.message_content if friend.message else ""
    if friend.message and friend.message.message_type == MessageType.random:
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        return random.choice(lines) if lines else SPARK_STICKER_TOKEN
    if friend.message and friend.message.message_type == MessageType.sticker:
        return SPARK_STICKER_TOKEN
    return content if content.strip() else SPARK_STICKER_TOKEN


def _mark_dispatch_skipped(message: str) -> None:
    global_state.mode = "dispatching"
    global_state.status_text = message
    global_state.current_step = "等待当前任务完成"
    global_state.blocked_point = "调度任务已在运行"


def _reset_dispatch_state() -> None:
    global_state.is_running = False
    global_state.mode = "idle"
    global_state.status_text = "系统空闲中"
    global_state.current_step = "等待下一次自动扫描"
    global_state.current_account = ""
    global_state.current_friend = ""
    global_state.total_tasks = 0
    global_state.completed_tasks = 0
    global_state.current_wait_seconds = 0


def _mark_friend_run(friend: Friend, current_time: datetime, result_status: RunStatus) -> None:
    friend.last_run_at = current_time
    friend.schedule_window = normalize_schedule_window(friend.schedule_window)
    if not friend.is_active:
        friend.next_run_at = None
        friend.consecutive_failures = 0
        return

    if friend.account.status == AccountStatus.invalid:
        # 账号凭证失效：不安排重试，等账号修复后由扫描重新生成计划。
        friend.next_run_at = None
        return

    if result_status == RunStatus.manual_review:
        # 人工复核：没有真正发送，不推进正常计划，短冷却后再检查一次。
        friend.consecutive_failures = 0
        friend.next_run_at = compute_retry_run_at(
            now=current_time,
            retry_cooldown_minutes=friend.retry_cooldown_minutes,
        )
        return

    if result_status == RunStatus.failed:
        friend.consecutive_failures += 1
        if friend.consecutive_failures <= friend.retry_limit:
            friend.next_run_at = compute_retry_run_at(
                now=current_time,
                retry_cooldown_minutes=friend.retry_cooldown_minutes,
            )
            return


    friend.consecutive_failures = 0
    friend.next_run_at = compute_friend_next_run_at(
        schedule_window=friend.schedule_window,
        now=current_time,
        frequency_days=friend.frequency_days,
        cooldown_minutes=friend.cooldown_minutes,
        last_run_at=friend.last_run_at,
    )

