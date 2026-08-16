from dataclasses import dataclass
from datetime import datetime


@dataclass
class SystemState:
    is_running: bool = False
    total_tasks: int = 0
    completed_tasks: int = 0
    status_text: str = "系统空闲中"
    mode: str = "idle"
    current_account: str = ""
    current_friend: str = ""
    current_step: str = "等待下一次自动扫描"
    last_scan_at: datetime | None = None
    next_scan_at: datetime | None = None
    scan_started_at: datetime | None = None
    last_scan_duration_ms: int = 0
    due_task_total: int = 0
    queued_task_total: int = 0
    current_wait_seconds: int = 0
    last_success_at: datetime | None = None
    last_success_summary: str = ""
    last_success_target: str = ""
    last_failure_at: datetime | None = None
    last_failure_reason: str = ""
    retry_remaining: int = 0
    blocked_point: str = ""
    last_error: str = ""


global_state = SystemState()
