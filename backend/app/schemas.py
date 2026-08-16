from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import AccountStatus, DispatchSource, MessageType, RunStatus


class AccountImportRequest(BaseModel):
    cookie_text: str = Field(min_length=10)


class AccountCookieUpdateRequest(BaseModel):
    cookie_text: str = Field(min_length=10)


class AccountUpdateRequest(BaseModel):
    nickname: str | None = None
    avatar_url: str | None = None
    proxy_url: str | None = None


class FriendToggleRequest(BaseModel):
    is_active: bool


class FriendScheduleUpdateRequest(BaseModel):
    schedule_window: str = Field(min_length=11, max_length=11)


class FriendStrategyUpdateRequest(BaseModel):
    schedule_window: str = Field(min_length=11, max_length=11)
    frequency_days: int = Field(ge=1, le=30)
    cooldown_minutes: int = Field(ge=0, le=1440)
    retry_limit: int = Field(ge=0, le=10)
    retry_cooldown_minutes: int = Field(ge=1, le=1440)


class MessageUpdateRequest(BaseModel):
    message_type: MessageType
    message_content: str = ""


class MessageBatchUpdateRequest(BaseModel):
    account_id: int | None = None
    message_type: MessageType
    message_content: str = ""


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    avatar_url: str
    nickname: str
    dy_id: str
    proxy_url: str | None = None
    status: AccountStatus
    status_reason: str
    last_checked_at: datetime | None
    cookie_expires_at: datetime | None = None
    cookie_updated_at: datetime | None = None
    updated_at: datetime
    friend_count: int = 0
    active_friend_count: int = 0


class FriendResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    friend_dy_id: str
    friend_nickname: str
    friend_avatar: str
    is_active: bool
    schedule_window: str
    frequency_days: int
    cooldown_minutes: int
    retry_limit: int
    retry_cooldown_minutes: int
    consecutive_failures: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_synced_at: datetime | None
    message_type: MessageType | None = None
    message_content: str = ""


class MessageResponse(BaseModel):
    id: int
    friend_id: int
    account_id: int
    account_name: str
    friend_name: str
    message_type: MessageType
    message_content: str
    account_status: AccountStatus
    schedule_window: str
    frequency_days: int
    cooldown_minutes: int
    retry_limit: int
    retry_cooldown_minutes: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    updated_at: datetime | None


class RunLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    friend_id: int
    status: RunStatus
    summary: str
    details: str
    created_at: datetime


class PaginatedLogsResponse(BaseModel):
    items: list[RunLogResponse]
    total: int


class DispatchTaskResponse(BaseModel):
    id: int
    friend_id: int
    account_id: int
    account_name: str
    friend_name: str
    source: DispatchSource
    status: RunStatus
    idempotency_key: str
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    summary: str
    details: str
    created_at: datetime
    updated_at: datetime


class PaginatedTasksResponse(BaseModel):
    items: list[DispatchTaskResponse]
    total: int


class SystemStatusResponse(BaseModel):
    is_running: bool
    total_tasks: int
    completed_tasks: int
    status_text: str
    mode: str
    current_account: str
    current_friend: str
    current_step: str
    last_scan_at: datetime | None
    next_scan_at: datetime | None
    due_task_total: int
    queued_task_total: int
    last_error: str
    scan_started_at: datetime | None
    last_scan_duration_ms: int
    current_wait_seconds: int
    last_success_at: datetime | None
    last_success_summary: str
    last_success_target: str
    last_failure_at: datetime | None
    last_failure_reason: str
    retry_remaining: int
    blocked_point: str


class AutoScheduleItem(BaseModel):
    friend_id: int
    account_id: int
    account_name: str
    friend_name: str
    friend_avatar: str
    schedule_window: str
    frequency_days: int
    cooldown_minutes: int
    retry_limit: int
    retry_cooldown_minutes: int
    consecutive_failures: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    message_type: MessageType | None = None
    current_status: str
    current_status_label: str
    current_status_reason: str
    last_result_status: RunStatus | None = None
    last_result_summary: str = ""
    last_result_details: str = ""
    last_result_at: datetime | None = None


class AutoScheduleSummary(BaseModel):
    enabled: bool
    scan_interval_seconds: int
    active_total: int
    scheduled_total: int
    overdue_total: int
    next_run_at: datetime | None
    items: list[AutoScheduleItem]


class SchedulePreviewOccurrence(BaseModel):
    friend_id: int
    account_id: int
    account_name: str
    friend_name: str
    planned_at: datetime
    schedule_window: str
    frequency_days: int
    message_type: MessageType | None = None


class SchedulePreviewDay(BaseModel):
    date: str
    label: str
    total: int
    items: list[SchedulePreviewOccurrence]


class SchedulePreviewResponse(BaseModel):
    days: int
    total: int
    items: list[SchedulePreviewDay]


class AutoScheduleSettingsUpdateRequest(BaseModel):
    enabled: bool


class AutoScheduleRegenerateRequest(BaseModel):
    account_id: int | None = None
    only_overdue: bool = True


class AutoScheduleBatchStrategyUpdateRequest(BaseModel):
    account_id: int | None = None
    schedule_window: str = Field(min_length=11, max_length=11)
    frequency_days: int = Field(ge=1, le=30)
    cooldown_minutes: int = Field(ge=0, le=1440)
    retry_limit: int = Field(ge=0, le=10)
    retry_cooldown_minutes: int = Field(ge=1, le=1440)


class DashboardSummary(BaseModel):
    account_total: int
    healthy_account_total: int
    invalid_account_total: int
    active_friend_total: int
    configured_message_total: int
    manual_review_job_total: int
    latest_logs: list[RunLogResponse]
