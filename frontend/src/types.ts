export type AccountStatus = "healthy" | "invalid" | "unknown";
export type MessageType = "fixed" | "random";
export type RunStatus = "pending" | "running" | "success" | "failed" | "manual_review" | "skipped";
export type DispatchSource = "manual" | "auto";

export interface Account {
  id: number;
  avatar_url: string;
  nickname: string;
  dy_id: string;
  proxy_url: string | null;
  status: AccountStatus;
  status_reason: string;
  last_checked_at: string | null;
  cookie_expires_at: string | null;
  cookie_updated_at: string | null;
  updated_at: string;
  friend_count: number;
  active_friend_count: number;
}

export interface Friend {
  id: number;
  account_id: number;
  friend_dy_id: string;
  friend_nickname: string;
  friend_avatar: string;
  is_active: boolean;
  schedule_window: string;
  frequency_days: number;
  cooldown_minutes: number;
  retry_limit: number;
  retry_cooldown_minutes: number;
  consecutive_failures: number;
  next_run_at: string | null;
  last_run_at: string | null;
  last_synced_at: string | null;
  message_type: MessageType | null;
  message_content: string;
}

export interface MessageRow {
  id: number;
  friend_id: number;
  account_id: number;
  account_name: string;
  friend_name: string;
  message_type: MessageType;
  message_content: string;
  account_status: AccountStatus;
  schedule_window: string;
  frequency_days: number;
  cooldown_minutes: number;
  retry_limit: number;
  retry_cooldown_minutes: number;
  next_run_at: string | null;
  last_run_at: string | null;
  updated_at: string | null;
}

export interface RunLog {
  id: number;
  friend_id: number;
  status: RunStatus;
  summary: string;
  details: string;
  created_at: string;
}

export type RunLogResponse = RunLog;

export interface PaginatedLogsResponse {
  items: RunLog[];
  total: number;
}

export interface DispatchTask {
  id: number;
  friend_id: number;
  account_id: number;
  account_name: string;
  friend_name: string;
  source: DispatchSource;
  status: RunStatus;
  idempotency_key: string;
  scheduled_for: string | null;
  started_at: string | null;
  finished_at: string | null;
  summary: string;
  details: string;
  created_at: string;
  updated_at: string;
}

export interface PaginatedTasksResponse {
  items: DispatchTask[];
  total: number;
}

export interface SystemStatusResponse {
  is_running: boolean;
  total_tasks: number;
  completed_tasks: number;
  status_text: string;
  mode: string;
  current_account: string;
  current_friend: string;
  current_step: string;
  last_scan_at: string | null;
  next_scan_at: string | null;
  due_task_total: number;
  queued_task_total: number;
  last_error: string;
  scan_started_at: string | null;
  last_scan_duration_ms: number;
  current_wait_seconds: number;
  last_success_at: string | null;
  last_success_summary: string;
  last_success_target: string;
  last_failure_at: string | null;
  last_failure_reason: string;
  retry_remaining: number;
  blocked_point: string;
}

export interface AutoScheduleItem {
  friend_id: number;
  account_id: number;
  account_name: string;
  friend_name: string;
  friend_avatar: string;
  schedule_window: string;
  frequency_days: number;
  cooldown_minutes: number;
  retry_limit: number;
  retry_cooldown_minutes: number;
  consecutive_failures: number;
  next_run_at: string | null;
  last_run_at: string | null;
  message_type: MessageType | null;
  current_status: string;
  current_status_label: string;
  current_status_reason: string;
  last_result_status: RunStatus | null;
  last_result_summary: string;
  last_result_details: string;
  last_result_at: string | null;
}

export interface AutoScheduleSummary {
  enabled: boolean;
  scan_interval_seconds: number;
  active_total: number;
  scheduled_total: number;
  overdue_total: number;
  next_run_at: string | null;
  items: AutoScheduleItem[];
}

export interface SchedulePreviewOccurrence {
  friend_id: number;
  account_id: number;
  account_name: string;
  friend_name: string;
  planned_at: string;
  schedule_window: string;
  frequency_days: number;
  message_type: MessageType | null;
}

export interface SchedulePreviewDay {
  date: string;
  label: string;
  total: number;
  items: SchedulePreviewOccurrence[];
}

export interface SchedulePreviewResponse {
  days: number;
  total: number;
  items: SchedulePreviewDay[];
}

export interface AutoScheduleSettingsUpdate {
  enabled: boolean;
}

export interface AutoScheduleRegenerateRequest {
  account_id?: number | null;
  only_overdue: boolean;
}

export interface FriendStrategyUpdate {
  account_id?: number | null;
  schedule_window: string;
  frequency_days: number;
  cooldown_minutes: number;
  retry_limit: number;
  retry_cooldown_minutes: number;
}

export interface DashboardSummary {
  account_total: number;
  healthy_account_total: number;
  invalid_account_total: number;
  active_friend_total: number;
  configured_message_total: number;
  manual_review_job_total: number;
  latest_logs: RunLog[];
}

export interface SystemSettingsResponse {
  app_name: string;
  api_prefix: string;
  admin_token_configured: boolean;
  scheduler_enabled: boolean;
  scheduler_scan_interval_seconds: number;
  manual_review_mode: boolean;
  sqlite_path: string;
  secret_key_path: string;
  cors_origins: string[];
  default_schedule_window: string;
}
