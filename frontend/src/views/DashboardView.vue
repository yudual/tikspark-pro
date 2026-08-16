<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import { api } from "../api/client";
import type { AutoScheduleSummary, DashboardSummary, SystemStatusResponse } from "../types";

const router = useRouter();
const summary = ref<DashboardSummary | null>(null);
const systemStatus = ref<SystemStatusResponse | null>(null);
const autoSchedule = ref<AutoScheduleSummary | null>(null);
const loading = ref(false);
const loadError = ref("");
let pollTimer: ReturnType<typeof setInterval>;

const engineModeLabel = computed(() => {
  const mode = systemStatus.value?.mode ?? "idle";
  const labels: Record<string, string> = {
    idle: "等待自动扫描",
    scanning: "扫描计划中",
    dispatching: "生成执行队列",
    jitter_wait: "防风控错峰",
    sending: "浏览器发送中",
    manual_review: "人工复核",
    error: "异常",
  };
  return labels[mode] ?? mode;
});

function formatDateTime(value: string | null | undefined) {
  if (!value) return "暂无";
  return new Date(value).toLocaleString();
}

function formatCountdown(value: string | null | undefined) {
  if (!value) return "暂无计划";
  const diffMs = new Date(value).getTime() - Date.now();
  if (diffMs <= 0) return "已到点";

  const totalMinutes = Math.floor(diffMs / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) return `${days}天 ${hours}小时后`;
  if (hours > 0) return `${hours}小时 ${minutes}分钟后`;
  return `${Math.max(minutes, 1)}分钟内`;
}

async function loadDashboard() {
  loading.value = true;
  try {
    const [summaryData, scheduleData, statusData] = await Promise.all([
      api.getDashboardSummary(),
      api.getAutoSchedule(),
      api.getSystemStatus(),
    ]);
    summary.value = summaryData;
    autoSchedule.value = scheduleData;
    systemStatus.value = statusData;
    loadError.value = "";
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : "加载看板失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadDashboard();
  pollTimer = setInterval(loadDashboard, 5000);
});

onUnmounted(() => {
  clearInterval(pollTimer);
});
</script>

<template>
  <div class="view-grid dashboard-compact" v-loading="loading">
    <el-alert
      v-if="loadError"
      class="dashboard-alert"
      :title="loadError"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="metrics-grid">
      <article class="metric-card">
        <p class="metric-label">托管账号数</p>
        <p class="metric-value">{{ summary?.account_total ?? 0 }}</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">健康账号</p>
        <p class="metric-value">{{ summary?.healthy_account_total ?? 0 }}</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">激活续火好友</p>
        <p class="metric-value">{{ summary?.active_friend_total ?? 0 }}</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">到点待跑</p>
        <p class="metric-value">{{ autoSchedule?.overdue_total ?? 0 }}</p>
      </article>
    </section>

    <section class="dashboard-quick-grid">
      <article class="panel-card dashboard-quick-card engine-card">
        <div class="section-head compact-head">
          <div>
            <h2>调度引擎状态</h2>
            <p class="section-subtitle">{{ systemStatus?.current_step || systemStatus?.status_text || "等待状态更新" }}</p>
          </div>
          <div class="engine-badge" :class="systemStatus?.mode">
            <span class="status-dot" :class="{ active: systemStatus?.is_running || systemStatus?.mode === 'scanning' }"></span>
            {{ engineModeLabel }}
          </div>
        </div>

        <div class="quick-facts">
          <div>
            <span class="meta">自动池</span>
            <strong>{{ systemStatus?.queued_task_total ?? 0 }}</strong>
          </div>
          <div>
            <span class="meta">本轮到点</span>
            <strong>{{ systemStatus?.due_task_total ?? 0 }}</strong>
          </div>
          <div>
            <span class="meta">下次扫描</span>
            <strong>{{ formatDateTime(systemStatus?.next_scan_at) }}</strong>
          </div>
        </div>

        <div class="dashboard-actions">
          <el-button type="primary" plain @click="router.push('/engine-status')">查看调度引擎</el-button>
        </div>
      </article>

      <article class="panel-card dashboard-quick-card auto-schedule-card">
        <div class="section-head compact-head">
          <div>
            <h2>自动续火计划</h2>
            <p class="section-subtitle">下一次执行：{{ formatDateTime(autoSchedule?.next_run_at) }}</p>
          </div>
          <div class="auto-summary">
            <span class="meta">最近一项</span>
            <strong>{{ formatCountdown(autoSchedule?.next_run_at) }}</strong>
          </div>
        </div>

        <div class="quick-facts">
          <div>
            <span class="meta">自动开关</span>
            <strong>{{ autoSchedule?.enabled ? "已开启" : "已关闭" }}</strong>
          </div>
          <div>
            <span class="meta">已排计划</span>
            <strong>{{ autoSchedule?.scheduled_total ?? 0 }}</strong>
          </div>
          <div>
            <span class="meta">扫描间隔</span>
            <strong>{{ autoSchedule?.scan_interval_seconds ?? 60 }} 秒</strong>
          </div>
        </div>

        <div class="dashboard-actions">
          <el-button type="primary" plain @click="router.push('/auto-schedule')">查看自动计划</el-button>
          <el-button @click="router.push('/manual-run')">去手动执行</el-button>
        </div>
      </article>
    </section>

    <section class="panel-card dashboard-log-card">
      <div class="section-head compact-head">
        <div>
          <h2>最近任务日志</h2>
          <p class="section-subtitle">只保留最近记录，完整列表在任务日志页。</p>
        </div>
        <el-button plain @click="router.push('/logs')">查看完整日志</el-button>
      </div>

      <div class="dense-list compact-log-list">
        <div v-for="log in summary?.latest_logs ?? []" :key="log.id" class="log-item compact-log-item">
          <strong>{{ log.summary }}</strong>
          <p class="meta">{{ log.details }}</p>
          <p class="meta">{{ new Date(log.created_at).toLocaleString() }}</p>
        </div>
        <el-empty v-if="(summary?.latest_logs?.length ?? 0) === 0" description="暂无任务记录" />
      </div>
    </section>
  </div>
</template>
