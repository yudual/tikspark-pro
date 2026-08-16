<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { api } from "../api/client";
import type {
  AutoScheduleItem,
  AutoScheduleSummary,
  FriendStrategyUpdate,
  SchedulePreviewResponse,
} from "../types";

const autoSchedule = ref<AutoScheduleSummary | null>(null);
const schedulePreview = ref<SchedulePreviewResponse | null>(null);
const loading = ref(false);
const loadError = ref("");
const updatingEnabled = ref(false);
const regenerating = ref(false);
const previewAccountId = ref<number | null>(null);
const expandedTaskIds = ref<Set<number>>(new Set());
const savingStrategies = reactive<Record<number, boolean>>({});
const strategyDrafts = reactive<Record<number, FriendStrategyUpdate>>({});
const batchSaving = ref(false);
const batchStrategy = reactive<FriendStrategyUpdate>({
  account_id: null,
  schedule_window: "06:00-08:00",
  frequency_days: 1,
  cooldown_minutes: 0,
  retry_limit: 2,
  retry_cooldown_minutes: 30,
});
let hasShownLoadError = false;
let pollTimer: ReturnType<typeof setInterval>;

function formatDateTime(value: string | null | undefined) {
  if (!value) return "暂无";
  return new Date(value).toLocaleString();
}

function formatTime(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatPreviewDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  return date.toLocaleDateString([], { month: "2-digit", day: "2-digit", weekday: "short" });
}

function formatCountdown(value: string | null | undefined) {
  if (!value) return "暂无计划";
  const diffMs = new Date(value).getTime() - Date.now();
  if (diffMs <= 0) return "已到点，等待扫描";

  const totalMinutes = Math.floor(diffMs / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) return `${days} 天 ${hours} 小时后`;
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟后`;
  return `${Math.max(minutes, 1)} 分钟内`;
}

function getResultLabel(status: AutoScheduleItem["last_result_status"]) {
  if (status === "success") return "发送成功";
  if (status === "failed") return "发送失败";
  if (status === "manual_review") return "人工复核";
  return "暂无结果";
}

function getTimelineIndex(status: string) {
  if (status === "queued") return 1;
  if (status === "jitter_wait") return 2;
  if (status === "sending") return 3;
  if (status === "retry_wait" || status === "manual_review") return 4;
  return 0;
}

function buildTimeline(item: AutoScheduleItem) {
  const finalLabel =
    item.current_status === "retry_wait"
      ? "等待重试"
      : item.current_status === "manual_review"
        ? "人工复核"
        : getResultLabel(item.last_result_status);

  return ["待扫描", "已入队", "错峰等待", "发送中", finalLabel].map((label, index) => {
    const currentIndex = getTimelineIndex(item.current_status);
    return {
      label,
      state: index < currentIndex ? "done" : index === currentIndex ? "active" : "pending",
    };
  });
}

function createStrategyDraft(item: AutoScheduleItem): FriendStrategyUpdate {
  return {
    account_id: item.account_id,
    schedule_window: item.schedule_window,
    frequency_days: item.frequency_days,
    cooldown_minutes: item.cooldown_minutes,
    retry_limit: item.retry_limit,
    retry_cooldown_minutes: item.retry_cooldown_minutes,
  };
}

function syncDrafts() {
  for (const item of autoSchedule.value?.items ?? []) {
    strategyDrafts[item.friend_id] = createStrategyDraft(item);
  }
  if ((autoSchedule.value?.items.length ?? 0) > 0) {
    Object.assign(batchStrategy, createStrategyDraft(autoSchedule.value!.items[0]));
    batchStrategy.account_id = null;
  }
}

function getBatchAccountOptions() {
  const map = new Map<number, string>();
  for (const item of autoSchedule.value?.items ?? []) {
    if (!map.has(item.account_id)) {
      map.set(item.account_id, item.account_name);
    }
  }
  return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
}

function getBatchTargetLabel() {
  if (batchStrategy.account_id == null) return "全部自动任务";
  return getBatchAccountOptions().find((account) => account.id === batchStrategy.account_id)?.name ?? "当前账号";
}

function getPreviewTargetLabel() {
  if (previewAccountId.value == null) return "全部账号";
  return getBatchAccountOptions().find((account) => account.id === previewAccountId.value)?.name ?? "当前账号";
}

function isTaskExpanded(friendId: number) {
  return expandedTaskIds.value.has(friendId);
}

function toggleTask(friendId: number) {
  const next = new Set(expandedTaskIds.value);
  if (next.has(friendId)) {
    next.delete(friendId);
  } else {
    next.add(friendId);
  }
  expandedTaskIds.value = next;
}

async function loadAutoSchedule(showLoading = false) {
  if (showLoading) loading.value = true;
  try {
    const [scheduleData, previewData] = await Promise.all([
      api.getAutoSchedule(),
      api.getAutoSchedulePreview(7, previewAccountId.value),
    ]);
    autoSchedule.value = scheduleData;
    schedulePreview.value = previewData;
    syncDrafts();
    loadError.value = "";
    hasShownLoadError = false;
  } catch (error) {
    const message = error instanceof Error ? error.message : "加载自动续火花计划失败";
    loadError.value = message;
    if (!hasShownLoadError) {
      ElMessage.error(message);
      hasShownLoadError = true;
    }
  } finally {
    loading.value = false;
  }
}

async function changePreviewAccount(value: number | null) {
  previewAccountId.value = value;
  await loadAutoSchedule(true);
}

async function toggleAutoSchedule(value: boolean) {
  updatingEnabled.value = true;
  try {
    autoSchedule.value = await api.updateAutoScheduleSettings(value);
    syncDrafts();
    ElMessage.success(value ? "自动续火花计划已开启" : "自动续火花计划已暂停");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新自动开关失败");
  } finally {
    updatingEnabled.value = false;
  }
}

function validateStrategy(strategy: FriendStrategyUpdate) {
  if (!strategy.schedule_window.trim()) {
    ElMessage.warning("请先填写时间段，例如 06:00-08:00");
    return false;
  }
  if (strategy.frequency_days < 1) {
    ElMessage.warning("续火间隔天数至少为 1 天");
    return false;
  }
  if (strategy.cooldown_minutes < 0) {
    ElMessage.warning("冷却分钟不能小于 0");
    return false;
  }
  if (strategy.retry_limit < 0) {
    ElMessage.warning("失败重试次数不能小于 0");
    return false;
  }
  if (strategy.retry_cooldown_minutes < 1) {
    ElMessage.warning("重试间隔分钟至少为 1");
    return false;
  }
  return true;
}

async function saveStrategy(friendId: number) {
  const draft = strategyDrafts[friendId];
  if (!draft || !validateStrategy(draft)) return;

  savingStrategies[friendId] = true;
  try {
    await api.updateFriendStrategy(friendId, draft);
    await loadAutoSchedule();
    ElMessage.success("自动策略已更新");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新自动策略失败");
  } finally {
    savingStrategies[friendId] = false;
  }
}

async function saveBatchStrategy() {
  if (!validateStrategy(batchStrategy)) return;
  batchSaving.value = true;
  try {
    autoSchedule.value = await api.batchUpdateAutoScheduleStrategy(batchStrategy);
    syncDrafts();
    await loadAutoSchedule();
    ElMessage.success(`已批量应用到 ${getBatchTargetLabel()}`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "批量应用自动策略失败");
  } finally {
    batchSaving.value = false;
  }
}

async function regenerateSchedule(onlyOverdue: boolean) {
  const title = onlyOverdue ? "重新生成过期计划？" : "重新生成全部计划？";
  const message = onlyOverdue
    ? "会把已到点或过期的任务重新排到未来时间，不影响尚未到点的任务。"
    : "会把所有启用好友的下一次执行时间重新排到未来，请确认当前策略已经配置好。";
  try {
    await ElMessageBox.confirm(message, title, {
      type: "warning",
      confirmButtonText: "确认重算",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }

  regenerating.value = true;
  try {
    autoSchedule.value = await api.regenerateAutoSchedule(onlyOverdue);
    syncDrafts();
    await loadAutoSchedule();
    ElMessage.success(onlyOverdue ? "过期计划已重新生成" : "全部计划已重新生成");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "重新生成计划失败");
  } finally {
    regenerating.value = false;
  }
}

onMounted(() => {
  loadAutoSchedule(true);
  pollTimer = setInterval(() => loadAutoSchedule(), 3000);
});

onUnmounted(() => {
  clearInterval(pollTimer);
});
</script>

<template>
  <div class="view-grid" v-loading="loading">
    <el-alert
      v-if="loadError"
      class="dashboard-alert"
      :title="loadError"
      type="warning"
      show-icon
      :closable="false"
    />

    <el-alert
      class="dashboard-alert"
      title="上云建议：先确认账号、消息和计划，再开启自动调度。Docker 默认不会自动执行，需在 1Panel 环境变量中开启 TIKSPARK_SCHEDULER_ENABLED。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="panel-card auto-schedule-card">
      <div class="section-head">
        <div>
          <h2>自动续火花计划</h2>
          <p class="section-subtitle">
            系统每 {{ autoSchedule?.scan_interval_seconds ?? 60 }} 秒扫描一次。开启后会在你设置的时间段内随机安排执行时间。
          </p>
        </div>
        <div class="auto-summary">
          <span class="meta">最近一项</span>
          <strong>{{ formatCountdown(autoSchedule?.next_run_at) }}</strong>
        </div>
      </div>

      <div class="auto-plan-strip">
        <div>
          <span class="meta">自动开关</span>
          <div class="schedule-switch-row">
            <el-switch
              :model-value="autoSchedule?.enabled ?? false"
              :loading="updatingEnabled"
              @update:model-value="toggleAutoSchedule"
            />
            <strong>{{ autoSchedule?.enabled ? "已开启" : "已关闭" }}</strong>
          </div>
          <span class="meta">关闭后不再自动扫描和入队</span>
        </div>
        <div>
          <span class="meta">已激活</span>
          <strong>{{ autoSchedule?.active_total ?? 0 }}</strong>
        </div>
        <div>
          <span class="meta">已排计划</span>
          <strong>{{ autoSchedule?.scheduled_total ?? 0 }}</strong>
        </div>
        <div>
          <span class="meta">到点待跑</span>
          <strong>{{ autoSchedule?.overdue_total ?? 0 }}</strong>
        </div>
        <div>
          <span class="meta">下一次执行</span>
          <strong>{{ formatDateTime(autoSchedule?.next_run_at) }}</strong>
        </div>
      </div>

      <div class="schedule-action-row">
        <el-button :loading="regenerating" @click="regenerateSchedule(true)">重算过期计划</el-button>
        <el-button :loading="regenerating" plain @click="regenerateSchedule(false)">重算全部计划</el-button>
      </div>

      <div class="schedule-helper">
        时间段格式为 <span class="mono">HH:MM-HH:MM</span>，例如 <span class="mono">09:30-11:00</span> 或
        <span class="mono">21:00-23:30</span>。
      </div>

      <section class="preview-card">
        <div class="preview-head">
          <div>
            <h3>未来 7 天计划</h3>
            <p class="meta">当前查看：{{ getPreviewTargetLabel() }}。按当前策略预估生成，不会立即创建或执行任务。</p>
          </div>
          <div class="preview-tools">
            <el-select
              :model-value="previewAccountId"
              class="preview-account-select"
              clearable
              placeholder="全部账号"
              @update:model-value="changePreviewAccount"
            >
              <el-option label="全部账号" :value="null" />
              <el-option
                v-for="account in getBatchAccountOptions()"
                :key="account.id"
                :label="account.name"
                :value="account.id"
              />
            </el-select>
            <strong>{{ schedulePreview?.total ?? 0 }} 次</strong>
          </div>
        </div>
        <div class="preview-days" v-if="(schedulePreview?.items?.length ?? 0) > 0">
          <article
            v-for="day in schedulePreview?.items ?? []"
            :key="day.date"
            class="preview-day"
          >
            <div class="preview-date">
              <strong>{{ formatPreviewDate(day.date) }}</strong>
              <span>{{ day.total }} 项</span>
            </div>
            <div class="preview-events">
              <div
                v-for="item in day.items.slice(0, 4)"
                :key="`${item.friend_id}-${item.planned_at}`"
                class="preview-event"
              >
                <span class="preview-time">{{ formatTime(item.planned_at) }}</span>
                <span class="preview-name">
                  <span class="preview-account">{{ item.account_name }}</span>
                  <span>{{ item.friend_name }}</span>
                </span>
              </div>
              <span v-if="day.items.length > 4" class="meta">还有 {{ day.items.length - 4 }} 项</span>
            </div>
          </article>
        </div>
        <el-empty v-else description="未来 7 天暂无计划" />
      </section>

      <section class="batch-strategy-card">
        <div class="batch-strategy-head">
          <div>
            <h3>批量策略</h3>
            <p class="meta">默认应用到全部自动任务，也可以只针对某一个账号生效。</p>
          </div>
          <el-button type="primary" :loading="batchSaving" @click="saveBatchStrategy">应用到当前目标</el-button>
        </div>
        <div class="strategy-grid">
          <label class="strategy-field">
            <span class="meta">目标账号</span>
            <el-select v-model="batchStrategy.account_id" clearable placeholder="全部自动任务">
              <el-option label="全部自动任务" :value="null" />
              <el-option
                v-for="account in getBatchAccountOptions()"
                :key="account.id"
                :label="account.name"
                :value="account.id"
              />
            </el-select>
          </label>
          <label class="strategy-field">
            <span class="meta">续火时段</span>
            <el-input v-model="batchStrategy.schedule_window" placeholder="06:00-08:00" />
          </label>
          <label class="strategy-field">
            <span class="meta">间隔天数</span>
            <el-input-number v-model="batchStrategy.frequency_days" :min="1" :max="30" />
          </label>
          <label class="strategy-field">
            <span class="meta">冷却分钟</span>
            <el-input-number v-model="batchStrategy.cooldown_minutes" :min="0" :max="1440" />
          </label>
          <label class="strategy-field">
            <span class="meta">失败重试次数</span>
            <el-input-number v-model="batchStrategy.retry_limit" :min="0" :max="10" />
          </label>
          <label class="strategy-field">
            <span class="meta">重试间隔分钟</span>
            <el-input-number v-model="batchStrategy.retry_cooldown_minutes" :min="1" :max="1440" />
          </label>
        </div>
      </section>

      <div class="schedule-list">
        <article
          v-for="item in autoSchedule?.items ?? []"
          :key="item.friend_id"
          class="schedule-row"
          :class="{ expanded: isTaskExpanded(item.friend_id) }"
        >
          <button class="schedule-summary-row" type="button" @click="toggleTask(item.friend_id)">
            <img :src="item.friend_avatar" alt="" class="avatar schedule-avatar" />
            <span class="schedule-summary-main">
              <strong>{{ item.account_name }}</strong>
              <span class="meta">{{ item.friend_name }}</span>
            </span>
            <span class="schedule-status-pill" :class="item.current_status">{{ item.current_status_label }}</span>
            <span class="schedule-summary-fact">
              <span class="meta">下一次</span>
              <strong>{{ formatDateTime(item.next_run_at) }}</strong>
            </span>
            <span class="schedule-summary-fact">
              <span class="meta">策略</span>
              <strong>{{ item.schedule_window }} / {{ item.frequency_days }} 天</strong>
            </span>
            <span class="schedule-summary-countdown">{{ formatCountdown(item.next_run_at) }}</span>
            <span class="schedule-expand-text">{{ isTaskExpanded(item.friend_id) ? "收起" : "展开" }}</span>
          </button>

          <div v-if="isTaskExpanded(item.friend_id)" class="schedule-detail">
            <div class="schedule-main schedule-main-rich">
              <p class="schedule-reason">{{ item.current_status_reason }}</p>

              <div class="schedule-timeline">
                <div
                  v-for="step in buildTimeline(item)"
                  :key="`${item.friend_id}-${step.label}`"
                  class="timeline-step"
                  :class="step.state"
                >
                  <span class="timeline-dot"></span>
                  <span class="timeline-label">{{ step.label }}</span>
                </div>
              </div>

              <div class="schedule-meta-grid">
                <div>
                  <span class="meta">下一次执行</span>
                  <strong>{{ formatDateTime(item.next_run_at) }}</strong>
                </div>
                <div>
                  <span class="meta">当前时段</span>
                  <strong>{{ item.schedule_window }}</strong>
                </div>
                <div>
                  <span class="meta">最近结果</span>
                  <strong>{{ getResultLabel(item.last_result_status) }}</strong>
                </div>
                <div>
                  <span class="meta">结果时间</span>
                  <strong>{{ formatDateTime(item.last_result_at) }}</strong>
                </div>
                <div>
                  <span class="meta">间隔天数</span>
                  <strong>{{ item.frequency_days }} 天</strong>
                </div>
                <div>
                  <span class="meta">冷却时间</span>
                  <strong>{{ item.cooldown_minutes }} 分钟</strong>
                </div>
                <div>
                  <span class="meta">重试策略</span>
                  <strong>{{ item.retry_limit }} 次 / {{ item.retry_cooldown_minutes }} 分钟</strong>
                </div>
                <div>
                  <span class="meta">连续失败</span>
                  <strong>{{ item.consecutive_failures }} 次</strong>
                </div>
              </div>

              <div class="schedule-result-box" :class="item.last_result_status ?? 'none'">
                <strong>{{ item.last_result_summary || "暂无最近执行结果" }}</strong>
                <p class="meta">{{ item.last_result_details || "当前还没有最近一次执行明细。" }}</p>
              </div>
            </div>

            <div class="schedule-side">
              <div class="strategy-grid per-item">
                <label class="strategy-field">
                  <span class="meta">续火时段</span>
                  <el-input v-model="strategyDrafts[item.friend_id].schedule_window" placeholder="06:00-08:00" />
                </label>
                <label class="strategy-field">
                  <span class="meta">间隔天数</span>
                  <el-input-number v-model="strategyDrafts[item.friend_id].frequency_days" :min="1" :max="30" />
                </label>
                <label class="strategy-field">
                  <span class="meta">冷却分钟</span>
                  <el-input-number v-model="strategyDrafts[item.friend_id].cooldown_minutes" :min="0" :max="1440" />
                </label>
                <label class="strategy-field">
                  <span class="meta">失败重试次数</span>
                  <el-input-number v-model="strategyDrafts[item.friend_id].retry_limit" :min="0" :max="10" />
                </label>
                <label class="strategy-field">
                  <span class="meta">重试间隔分钟</span>
                  <el-input-number v-model="strategyDrafts[item.friend_id].retry_cooldown_minutes" :min="1" :max="1440" />
                </label>
              </div>
              <el-button
                plain
                :loading="savingStrategies[item.friend_id]"
                @click="saveStrategy(item.friend_id)"
              >
                保存这条策略
              </el-button>
            </div>
          </div>
        </article>
        <el-empty v-if="(autoSchedule?.items?.length ?? 0) === 0" description="暂无自动续火花计划" />
      </div>
    </section>
  </div>
</template>
