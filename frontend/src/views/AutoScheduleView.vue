<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Refresh, Setting, Calendar, ArrowDown, ArrowUp } from "@element-plus/icons-vue";

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

function createBatchDraft(): FriendStrategyUpdate {
  const first = autoSchedule.value?.items?.[0];
  if (!first) return { ...batchStrategy };
  return {
    account_id: null,
    schedule_window: first.schedule_window,
    frequency_days: first.frequency_days,
    cooldown_minutes: first.cooldown_minutes,
    retry_limit: first.retry_limit,
    retry_cooldown_minutes: first.retry_cooldown_minutes,
  };
}

function syncBatchDraft() {
  Object.assign(batchStrategy, createBatchDraft());
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
    syncBatchDraft();
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
    syncBatchDraft();
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

async function saveBatchStrategy() {
  if (!validateStrategy(batchStrategy)) return;
  batchSaving.value = true;
  try {
    autoSchedule.value = await api.batchUpdateAutoScheduleStrategy(batchStrategy);
    syncBatchDraft();
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
    syncBatchDraft();
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

    <!-- 顶部主状态控制卡片 -->
    <section class="panel-card auto-schedule-hero-card">
      <div class="hero-top-row">
        <div>
          <h2>自动续火花调度中心</h2>
          <p class="section-subtitle">
            调度引擎每 {{ autoSchedule?.scan_interval_seconds ?? 60 }} 秒扫描一次。开启后将在您设定的时段内错峰自动派发。
          </p>
        </div>
        <div class="hero-switch-box">
          <span class="meta">自动计划全局总控</span>
          <div class="switch-inner">
            <el-switch
              :model-value="autoSchedule?.enabled ?? false"
              :loading="updatingEnabled"
              size="large"
              active-text="运行中"
              inactive-text="已暂停"
              inline-prompt
              @update:model-value="toggleAutoSchedule"
            />
          </div>
        </div>
      </div>

      <!-- 核心调度数据条 -->
      <div class="schedule-stat-strip">
        <div class="stat-box">
          <span class="meta">已激活好友</span>
          <strong>{{ autoSchedule?.active_total ?? 0 }} 位</strong>
        </div>
        <div class="stat-box">
          <span class="meta">已排定计划</span>
          <strong>{{ autoSchedule?.scheduled_total ?? 0 }} 项</strong>
        </div>
        <div class="stat-box">
          <span class="meta">到点待跑</span>
          <strong style="color: var(--primary)">{{ autoSchedule?.overdue_total ?? 0 }} 项</strong>
        </div>
        <div class="stat-box">
          <span class="meta">下一次执行倒计时</span>
          <strong style="color: var(--success)">{{ formatCountdown(autoSchedule?.next_run_at) }}</strong>
        </div>
      </div>

      <div class="schedule-actions-bar">
        <div class="btn-group">
          <el-button type="primary" plain :loading="regenerating" :icon="Refresh" @click="regenerateSchedule(true)">
            重算过期计划
          </el-button>
          <el-button plain :loading="regenerating" :icon="Setting" @click="regenerateSchedule(false)">
            重算全部计划
          </el-button>
        </div>
        <span class="helper-text">
          💡 时段格式为 <span class="mono">HH:MM-HH:MM</span>（如 <span class="mono">06:00-08:00</span>），系统将在此时段内随机抽取时间执行。
        </span>
      </div>
    </section>

    <!-- 未来 7 天日历预估视图 -->
    <section class="panel-card">
      <div class="preview-head">
        <div>
          <h2>未来 7 天计划预览</h2>
          <p class="section-subtitle">当前查看目标：{{ getPreviewTargetLabel() }}。系统根据当前策略预估排列，不会提前创建真实任务。</p>
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
          <el-tag size="large" type="info" effect="plain">未来 7 天共 {{ schedulePreview?.total ?? 0 }} 项</el-tag>
        </div>
      </div>

      <div class="preview-days-grid" v-if="(schedulePreview?.items?.length ?? 0) > 0">
        <article
          v-for="day in schedulePreview?.items ?? []"
          :key="day.date"
          class="preview-day-card"
        >
          <div class="day-card-header">
            <strong>{{ formatPreviewDate(day.date) }}</strong>
            <span class="day-count-badge">{{ day.total }} 项</span>
          </div>
          <div class="day-events-list">
            <div
              v-for="item in day.items.slice(0, 4)"
              :key="`${item.friend_id}-${item.planned_at}`"
              class="day-event-chip"
            >
              <span class="event-time mono">{{ formatTime(item.planned_at) }}</span>
              <div class="event-name-block">
                <span class="event-friend">{{ item.friend_name }}</span>
                <span class="event-account">{{ item.account_name }}</span>
              </div>
            </div>
            <div v-if="day.items.length > 4" class="more-events-tag">
              + 另外 {{ day.items.length - 4 }} 位好友
            </div>
          </div>
        </article>
      </div>
      <el-empty v-else description="未来 7 天暂无计划" :image-size="70" />
    </section>

    <!-- 批量策略配置面板 -->
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>批量策略配置</h2>
          <p class="section-subtitle">配置每日续火时间窗口、执行间隔、风控冷却与失败重试策略。</p>
        </div>
        <el-button type="primary" :loading="batchSaving" @click="saveBatchStrategy">
          保存并应用到：{{ getBatchTargetLabel() }}
        </el-button>
      </div>

      <div class="strategy-form-grid">
        <div class="strategy-form-item">
          <span class="meta">生效目标账号</span>
          <el-select v-model="batchStrategy.account_id" clearable placeholder="全部自动任务">
            <el-option label="全部自动任务" :value="null" />
            <el-option
              v-for="account in getBatchAccountOptions()"
              :key="account.id"
              :label="account.name"
              :value="account.id"
            />
          </el-select>
        </div>
        <div class="strategy-form-item">
          <span class="meta">续火时间窗口</span>
          <el-input v-model="batchStrategy.schedule_window" placeholder="06:00-08:00" />
        </div>
        <div class="strategy-form-item">
          <span class="meta">执行间隔天数</span>
          <el-input-number v-model="batchStrategy.frequency_days" :min="1" :max="30" style="width: 100%" />
        </div>
        <div class="strategy-form-item">
          <span class="meta">风控冷却 (分钟)</span>
          <el-input-number v-model="batchStrategy.cooldown_minutes" :min="0" :max="1440" style="width: 100%" />
        </div>
        <div class="strategy-form-item">
          <span class="meta">失败重试上限</span>
          <el-input-number v-model="batchStrategy.retry_limit" :min="0" :max="10" style="width: 100%" />
        </div>
        <div class="strategy-form-item">
          <span class="meta">重试间隔 (分钟)</span>
          <el-input-number v-model="batchStrategy.retry_cooldown_minutes" :min="1" :max="1440" style="width: 100%" />
        </div>
      </div>
    </section>

    <!-- 好友独立计划列表与时间线 -->
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>好友执行计划列表</h2>
          <p class="section-subtitle">点击任意条目可展开查看详细状态流转时间线与参数明细。</p>
        </div>
      </div>

      <div class="schedule-items-list">
        <article
          v-for="item in autoSchedule?.items ?? []"
          :key="item.friend_id"
          class="schedule-item-card"
          :class="{ expanded: isTaskExpanded(item.friend_id) }"
        >
          <div class="schedule-summary-bar" @click="toggleTask(item.friend_id)">
            <el-avatar :size="42" :src="item.friend_avatar" class="avatar schedule-avatar">
              <span>{{ item.friend_name.charAt(0) }}</span>
            </el-avatar>
            <div class="summary-target">
              <strong>{{ item.friend_name }}</strong>
              <span class="meta">{{ item.account_name }}</span>
            </div>
            <div class="summary-status">
              <span class="schedule-status-pill" :class="item.current_status">{{ item.current_status_label }}</span>
            </div>
            <div class="summary-meta-cell">
              <span class="meta">计划窗口</span>
              <strong>{{ item.schedule_window }}</strong>
            </div>
            <div class="summary-meta-cell">
              <span class="meta">下次执行</span>
              <strong>{{ formatDateTime(item.next_run_at) }}</strong>
            </div>
            <div class="summary-countdown">
              {{ formatCountdown(item.next_run_at) }}
            </div>
            <div class="expand-btn">
              <el-icon><component :is="isTaskExpanded(item.friend_id) ? ArrowUp : ArrowDown" /></el-icon>
            </div>
          </div>

          <!-- 展开详情面板 -->
          <div v-if="isTaskExpanded(item.friend_id)" class="schedule-detail-panel">
            <p class="schedule-reason-text" v-if="item.current_status_reason">{{ item.current_status_reason }}</p>

            <!-- 状态流转时间线 -->
            <div class="schedule-timeline-track">
              <div
                v-for="step in buildTimeline(item)"
                :key="`${item.friend_id}-${step.label}`"
                class="timeline-track-step"
                :class="step.state"
              >
                <span class="timeline-step-dot"></span>
                <span class="timeline-step-label">{{ step.label }}</span>
              </div>
            </div>

            <!-- 参数属性网格 -->
            <div class="schedule-params-grid">
              <div class="param-box">
                <span class="meta">下一次执行：</span>
                <strong>{{ formatDateTime(item.next_run_at) }}</strong>
              </div>
              <div class="param-box">
                <span class="meta">设定时段：</span>
                <strong>{{ item.schedule_window }}</strong>
              </div>
              <div class="param-box">
                <span class="meta">最近结果：</span>
                <strong>{{ getResultLabel(item.last_result_status) }}</strong>
              </div>
              <div class="param-box">
                <span class="meta">结果时间：</span>
                <strong>{{ formatDateTime(item.last_result_at) }}</strong>
              </div>
              <div class="param-box">
                <span class="meta">间隔天数：</span>
                <strong>每 {{ item.frequency_days }} 天</strong>
              </div>
              <div class="param-box">
                <span class="meta">风控冷却：</span>
                <strong>{{ item.cooldown_minutes }} 分钟</strong>
              </div>
              <div class="param-box">
                <span class="meta">重试机制：</span>
                <strong>上限 {{ item.retry_limit }} 次 / 间隔 {{ item.retry_cooldown_minutes }} 分钟</strong>
              </div>
              <div class="param-box">
                <span class="meta">连续失败：</span>
                <strong :style="{ color: item.consecutive_failures > 0 ? 'var(--danger)' : 'inherit' }">
                  {{ item.consecutive_failures }} 次
                </strong>
              </div>
            </div>

            <!-- 结果描述框 -->
            <div class="schedule-result-desc" :class="item.last_result_status ?? 'none'">
              <strong>{{ item.last_result_summary || "暂无最近执行结果" }}</strong>
              <p>{{ item.last_result_details || "任务将在到达计划时段后由引擎自动调度执行。" }}</p>
            </div>
          </div>
        </article>

        <el-empty v-if="(autoSchedule?.items?.length ?? 0) === 0" description="暂无自动续火花计划" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.auto-schedule-hero-card {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.hero-switch-box {
  background: var(--bg-surface-subtle);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 10px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.schedule-stat-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.stat-box {
  background: var(--bg-surface-subtle);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-box strong {
  font-size: 18px;
  color: var(--text-main);
}

.schedule-actions-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.btn-group {
  display: flex;
  gap: 10px;
}

.helper-text {
  font-size: 13px;
  color: var(--text-muted);
}

/* 7 天日历预览 */
.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.preview-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}

.preview-account-select {
  width: 180px;
}

.preview-days-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.preview-day-card {
  background: #f8fafc;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.day-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 8px;
}

.day-card-header strong {
  font-size: 13px;
  color: var(--text-main);
}

.day-count-badge {
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-light);
  padding: 2px 6px;
  border-radius: var(--radius-full);
  font-weight: 600;
}

.day-events-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.day-event-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  background: #ffffff;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-light);
}

.event-time {
  font-size: 11px;
  color: var(--primary);
  font-weight: 700;
  flex-shrink: 0;
}

.event-name-block {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.event-friend {
  font-weight: 600;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-account {
  font-size: 10px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.more-events-tag {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  padding-top: 2px;
}

/* 策略表单 */
.strategy-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}

.strategy-form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 计划列表与时间线 */
.schedule-items-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.schedule-item-card {
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: all 0.15s ease;
}

.schedule-item-card:hover {
  border-color: #cbd5e1;
}

.schedule-summary-bar {
  display: grid;
  grid-template-columns: 42px minmax(160px, 1.2fr) 110px minmax(120px, 0.8fr) minmax(170px, 1fr) 130px 40px;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  cursor: pointer;
  background: #ffffff;
  transition: background-color 0.15s ease;
}

.schedule-summary-bar:hover {
  background: #f8fafc;
}

.summary-target {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.summary-target strong {
  font-size: 14px;
  color: var(--text-main);
}

.summary-meta-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.summary-meta-cell strong {
  font-size: 13px;
}

.summary-countdown {
  font-size: 13px;
  font-weight: 700;
  color: var(--primary);
  text-align: right;
}

.expand-btn {
  display: flex;
  justify-content: flex-end;
  color: var(--text-muted);
}

.schedule-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}

.schedule-status-pill.waiting_scan,
.schedule-status-pill.unscheduled {
  background: var(--bg-surface-subtle);
  color: var(--text-muted);
}

.schedule-status-pill.queued,
.schedule-status-pill.jitter_wait {
  background: var(--warning-light);
  color: var(--warning);
}

.schedule-status-pill.sending {
  background: var(--success-light);
  color: var(--success);
}

.schedule-status-pill.retry_wait,
.schedule-status-pill.manual_review {
  background: var(--danger-light);
  color: var(--danger);
}

/* 详情展开区 */
.schedule-detail-panel {
  border-top: 1px solid var(--border-light);
  background: #f8fafc;
  padding: 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.schedule-reason-text {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.schedule-timeline-track {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.timeline-track-step {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.timeline-step-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #cbd5e1;
}

.timeline-step-label {
  font-size: 12px;
  color: var(--text-muted);
}

.timeline-track-step.done .timeline-step-dot,
.timeline-track-step.active .timeline-step-dot {
  background: var(--primary);
}

.timeline-track-step.done .timeline-step-label,
.timeline-track-step.active .timeline-step-label {
  color: var(--text-main);
  font-weight: 600;
}

.schedule-params-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
}

.param-box {
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.schedule-result-desc {
  background: #ffffff;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  font-size: 13px;
}

.schedule-result-desc strong {
  display: block;
  margin-bottom: 4px;
  color: var(--text-main);
}

.schedule-result-desc p {
  color: var(--text-muted);
  margin: 0;
}

.schedule-result-desc.success {
  border-color: rgba(16, 185, 129, 0.3);
  background: #f0fdf4;
}

.schedule-result-desc.failed {
  border-color: rgba(239, 68, 68, 0.3);
  background: #fef2f2;
}

@media (max-width: 900px) {
  .schedule-summary-bar {
    grid-template-columns: 42px minmax(0, 1fr) auto;
  }
  .summary-meta-cell,
  .summary-countdown {
    display: none;
  }
}
</style>
