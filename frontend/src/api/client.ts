import type {
  Account,
  AutoScheduleSummary,
  DashboardSummary,
  DispatchSource,
  Friend,
  FriendStrategyUpdate,
  MessageRow,
  MessageType,
  PaginatedLogsResponse,
  PaginatedTasksResponse,
  RunLogResponse,
  RunStatus,
  SchedulePreviewResponse,
  SystemSettingsResponse,
  SystemStatusResponse,
} from "../types";

const TOKEN_STORAGE_KEY = "tikspark_admin_token";

export function getAdminToken() {
  return localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
}

export function setAdminToken(token: string) {
  const trimmed = token.trim();
  if (trimmed) {
    localStorage.setItem(TOKEN_STORAGE_KEY, trimmed);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function clearAdminToken() {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const token = getAdminToken();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  try {
    response = await fetch(url, {
      ...init,
      headers,
    });
  } catch {
    throw new Error("无法连接后端服务，请确认 8010 接口服务正在运行。");
  }

  if (!response.ok) {
    const text = await response.text();
    if (response.status === 401) {
      clearAdminToken();
      throw new Error("管理员访问令牌不正确，或与服务器里配置的 TIKSPARK_ADMIN_TOKEN 不一致。");
    }
    if (response.status >= 500) {
      throw new Error("后端服务异常或未启动，请确认 8010 接口服务正在运行。");
    }
    let detail = "";
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? "";
    } catch {
      detail = text;
    }
    throw new Error(detail || `请求失败：${response.status}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  getSystemStatus() {
    return request<SystemStatusResponse>("/api/dashboard/system-status");
  },
  getDashboardSummary() {
    return request<DashboardSummary>("/api/dashboard/summary");
  },
  getAutoSchedule() {
    return request<AutoScheduleSummary>("/api/schedule");
  },
  getAutoSchedulePreview(days: number = 7, accountId?: number | null) {
    const params = new URLSearchParams({ days: days.toString() });
    if (accountId != null) params.append("account_id", accountId.toString());
    return request<SchedulePreviewResponse>(`/api/schedule/preview?${params.toString()}`);
  },
  updateAutoScheduleSettings(enabled: boolean) {
    return request<AutoScheduleSummary>("/api/schedule/settings", {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
  },
  regenerateAutoSchedule(onlyOverdue = true, accountId?: number | null) {
    return request<AutoScheduleSummary>("/api/schedule/regenerate", {
      method: "POST",
      body: JSON.stringify({
        account_id: accountId ?? null,
        only_overdue: onlyOverdue,
      }),
    });
  },
  batchUpdateAutoScheduleStrategy(strategy: FriendStrategyUpdate) {
    return request<AutoScheduleSummary>("/api/schedule/batch-strategy", {
      method: "PATCH",
      body: JSON.stringify(strategy),
    });
  },
  listLogs(page: number = 1, limit: number = 50, accountId?: number) {
    let url = `/api/logs?page=${page}&limit=${limit}`;
    if (accountId) {
      url += `&account_id=${accountId}`;
    }
    return request<PaginatedLogsResponse>(url);
  },
  listTasks(
    page: number = 1,
    limit: number = 50,
    accountId?: number,
    status?: RunStatus,
    source?: DispatchSource,
  ) {
    const params = new URLSearchParams({
      page: page.toString(),
      limit: limit.toString(),
    });
    if (accountId) params.append("account_id", accountId.toString());
    if (status) params.append("status", status);
    if (source) params.append("source", source);
    return request<PaginatedTasksResponse>(`/api/run/tasks?${params.toString()}`);
  },
  runTasks(accountId?: number, friendId?: number, isAutoCron: boolean = false) {
    let url = "/api/run/tasks";
    const params = new URLSearchParams();
    if (accountId) params.append("account_id", accountId.toString());
    if (friendId) params.append("friend_id", friendId.toString());
    if (isAutoCron) params.append("is_auto_cron", "true");
    if (params.toString()) url += `?${params.toString()}`;

    return request<{ message: string }>(url, {
      method: "POST",
    });
  },
  listAccounts() {
    return request<Account[]>("/api/accounts");
  },
  importAccount(cookieText: string) {
    return request<Account>("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ cookie_text: cookieText }),
    });
  },
  updateAccount(accountId: number, data: { nickname?: string; avatar_url?: string; proxy_url?: string }) {
    return request<Account>(`/api/accounts/${accountId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },
  updateAccountCookie(accountId: number, cookieText: string) {
    return request<Account>(`/api/accounts/${accountId}/cookie`, {
      method: "PUT",
      body: JSON.stringify({ cookie_text: cookieText }),
    });
  },
  deleteAccount(accountId: number) {
    const token = getAdminToken();
    return fetch(`/api/accounts/${accountId}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then((res) => {
      if (!res.ok) throw new Error("删除失败");
    });
  },
  listFriends(accountId: number) {
    return request<Friend[]>(`/api/accounts/${accountId}/friends`);
  },
  refreshFriends(accountId: number) {
    return request<Friend[]>(`/api/accounts/${accountId}/refresh-friends`, {
      method: "POST",
    });
  },
  toggleFriend(friendId: number, isActive: boolean) {
    return request<Friend>(`/api/accounts/friends/${friendId}/toggle`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: isActive }),
    });
  },
  updateFriendSchedule(friendId: number, scheduleWindow: string) {
    return request<Friend>(`/api/accounts/friends/${friendId}/schedule`, {
      method: "PATCH",
      body: JSON.stringify({ schedule_window: scheduleWindow }),
    });
  },
  updateFriendStrategy(friendId: number, strategy: FriendStrategyUpdate) {
    return request<Friend>(`/api/accounts/friends/${friendId}/strategy`, {
      method: "PATCH",
      body: JSON.stringify(strategy),
    });
  },
  listMessages() {
    return request<MessageRow[]>("/api/messages");
  },
  updateMessage(friendId: number, messageType: MessageType, messageContent: string) {
    return request<MessageRow>(`/api/messages/friend/${friendId}`, {
      method: "PUT",
      body: JSON.stringify({
        message_type: messageType,
        message_content: messageContent,
      }),
    });
  },
  batchUpdateMessages(messageType: MessageType, messageContent: string, accountId?: number) {
    return request<{ message: string; updated_count: number }>("/api/messages/batch-update", {
      method: "POST",
      body: JSON.stringify({
        account_id: accountId,
        message_type: messageType,
        message_content: messageContent,
      }),
    });
  },
  getSystemSettings() {
    return request<SystemSettingsResponse>("/api/system/settings");
  },
};

export type { RunLogResponse };
