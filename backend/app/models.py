from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class AccountStatus(str, Enum):
    healthy = "healthy"
    invalid = "invalid"
    unknown = "unknown"


class MessageType(str, Enum):
    fixed = "fixed"
    random = "random"


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    manual_review = "manual_review"
    skipped = "skipped"


class DispatchSource(str, Enum):
    manual = "manual"
    auto = "auto"


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    avatar_url: Mapped[str] = mapped_column(String(255), default="")
    nickname: Mapped[str] = mapped_column(String(100), default="未命名账号")
    dy_id: Mapped[str] = mapped_column(String(100), default="")
    cookie_text: Mapped[str] = mapped_column(Text)
    status: Mapped[AccountStatus] = mapped_column(
        SqlEnum(AccountStatus), default=AccountStatus.unknown
    )
    status_reason: Mapped[str] = mapped_column(String(255), default="")
    proxy_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cookie_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cookie_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    friends: Mapped[list["Friend"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Friend(TimestampMixin, Base):
    __tablename__ = "friends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    friend_dy_id: Mapped[str] = mapped_column(String(100), default="")
    friend_nickname: Mapped[str] = mapped_column(String(100), default="未命名好友")
    friend_avatar: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_window: Mapped[str] = mapped_column(String(20), default="06:00-08:00")
    frequency_days: Mapped[int] = mapped_column(Integer, default=1)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=0)
    retry_limit: Mapped[int] = mapped_column(Integer, default=2)
    retry_cooldown_minutes: Mapped[int] = mapped_column(Integer, default=30)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    account: Mapped[Account] = relationship(back_populates="friends")
    message: Mapped["Message | None"] = relationship(
        back_populates="friend", cascade="all, delete-orphan", uselist=False
    )
    run_logs: Mapped[list["RunLog"]] = relationship(
        back_populates="friend", cascade="all, delete-orphan"
    )
    dispatch_tasks: Mapped[list["DispatchTask"]] = relationship(
        back_populates="friend", cascade="all, delete-orphan"
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    friend_id: Mapped[int] = mapped_column(ForeignKey("friends.id"), unique=True, index=True)
    message_type: Mapped[MessageType] = mapped_column(
        SqlEnum(MessageType), default=MessageType.fixed
    )
    message_content: Mapped[str] = mapped_column(Text, default="")

    friend: Mapped[Friend] = relationship(back_populates="message")


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    friend_id: Mapped[int] = mapped_column(ForeignKey("friends.id"), index=True)
    status: Mapped[RunStatus] = mapped_column(SqlEnum(RunStatus), default=RunStatus.pending)
    summary: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.utcnow() + timedelta(hours=8),
    )

    friend: Mapped[Friend] = relationship(back_populates="run_logs")


class DispatchTask(Base):
    __tablename__ = "dispatch_tasks"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_dispatch_tasks_idempotency_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    friend_id: Mapped[int] = mapped_column(ForeignKey("friends.id"), index=True)
    source: Mapped[DispatchSource] = mapped_column(SqlEnum(DispatchSource), default=DispatchSource.manual)
    status: Mapped[RunStatus] = mapped_column(SqlEnum(RunStatus), default=RunStatus.pending, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summary: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=8))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.utcnow() + timedelta(hours=8),
        onupdate=lambda: datetime.utcnow() + timedelta(hours=8),
    )

    friend: Mapped[Friend] = relationship(back_populates="dispatch_tasks")


class DispatchLock(Base):
    __tablename__ = "dispatch_locks"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner: Mapped[str] = mapped_column(String(120), default="")
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=8))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
