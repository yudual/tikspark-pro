from __future__ import annotations

import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import DispatchLock, DispatchSource, DispatchTask, Friend, RunStatus
from .schedule_service import get_local_now


DISPATCH_LOCK_NAME = "dispatch_active_messages"


@dataclass(frozen=True)
class DispatchLockHandle:
    name: str
    owner: str


def acquire_dispatch_lock(db: Session, ttl_seconds: int = 300) -> DispatchLockHandle | None:
    now = get_local_now()
    owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
    existing = db.get(DispatchLock, DISPATCH_LOCK_NAME)
    if existing and existing.expires_at > now:
        return None

    if existing is None:
        db.add(
            DispatchLock(
                name=DISPATCH_LOCK_NAME,
                owner=owner,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
        )
    else:
        existing.owner = owner
        existing.acquired_at = now
        existing.expires_at = now + timedelta(seconds=ttl_seconds)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None

    return DispatchLockHandle(name=DISPATCH_LOCK_NAME, owner=owner)


def release_dispatch_lock(db: Session, handle: DispatchLockHandle | None) -> None:
    if handle is None:
        return
    existing = db.get(DispatchLock, handle.name)
    if existing and existing.owner == handle.owner:
        db.delete(existing)
        db.commit()


def is_dispatch_locked(db: Session) -> bool:
    existing = db.get(DispatchLock, DISPATCH_LOCK_NAME)
    return bool(existing and existing.expires_at > get_local_now())


def create_dispatch_task(
    db: Session,
    friend: Friend,
    *,
    source: DispatchSource,
    scheduled_for: datetime | None,
) -> DispatchTask:
    idempotency_key = _build_idempotency_key(friend, source, scheduled_for)
    existing = (
        db.query(DispatchTask)
        .filter(DispatchTask.idempotency_key == idempotency_key)
        .one_or_none()
    )
    if existing is not None:
        return existing

    task = DispatchTask(
        friend_id=friend.id,
        source=source,
        status=RunStatus.pending,
        idempotency_key=idempotency_key,
        scheduled_for=scheduled_for,
        summary="等待执行",
        details="任务已进入调度队列。",
    )
    db.add(task)
    db.flush()
    return task


def mark_task_running(task: DispatchTask) -> None:
    now = get_local_now()
    task.status = RunStatus.running
    task.started_at = now
    task.updated_at = now
    task.summary = "执行中"
    task.details = "浏览器自动化任务已开始执行。"


def mark_task_finished(task: DispatchTask, status: RunStatus, summary: str, details: str) -> None:
    now = get_local_now()
    task.status = status
    task.summary = summary
    task.details = details
    task.finished_at = now
    task.updated_at = now


def mark_task_skipped(task: DispatchTask, summary: str, details: str) -> None:
    mark_task_finished(task, RunStatus.skipped, summary, details)


def _build_idempotency_key(
    friend: Friend,
    source: DispatchSource,
    scheduled_for: datetime | None,
) -> str:
    if source == DispatchSource.auto and scheduled_for is not None:
        bucket = scheduled_for.strftime("%Y%m%d%H%M")
    else:
        bucket = uuid.uuid4().hex
    return f"{source.value}:{friend.id}:{bucket}"
