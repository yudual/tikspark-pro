<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import { api } from "../api/client";
import type { DashboardSummary, SystemStatusResponse } from "../types";

const router = useRouter();
const summary = ref<DashboardSummary | null>(null);
const systemStatus = ref<SystemStatusResponse | null>(null);
const loading = ref(false);
const loadError = ref("");
let pollTimer: ReturnType<typeof setInterval>;

const engineModeLabel = computed(() => {
  const mode = systemStatus.value?.mode ?? "idle";
  const labels: Record<string, string> = {
    idle: "空闲",
    scanning: "扫描中",
    dispatching: "入队中",
    jitter_wait: "错峰等待",
    sending: "发送中",
    manual_review: "人工复核",
    error: "异常",
  };
  return labels[mode] ?? mode;
});

const abnormalLogs = computed(() =>
  (summary.value?.latest_logs ?? []).filter(
    (log) => log.status === "failed" || log.status === "manual_review",
  ).slice(0, 5),
);

function formatDateTime(value: string | null | undefined) {
  if (!value) return "暂无";
  return new Date(value).toLocaleString();
}

async function loadDashboard() {
  loading.value = true;
  try {
    const [summaryData, statusData] = await Promise.all([
      api.getDashboardSummary(),
      api.getSystemStatus(),
    ]);
    summary.value = summaryData;
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
        <p class="metric-label">人工复核待处理</p>
        <p class="metric-value">{{ summary?.manual_review_job_total ?? 0 }}</p>
      </article>
    </section>

    <section class="panel-card engine-strip-card">
      <div class="engine-strip-main">
        <div class="engine-badge" :class="systemStatus?.mode">
          <span class="status-dot" :class="{ active: systemStatus?.is_running || systemStatus?.mode === 'scanning' }"></span>
          {{ engineModeLabel }}
        </div>
        <div class="engine-step">
          <span class="meta">当前步骤</span>
          <strong>{{ systemStatus?.current_step || systemStatus?.status_text || "等待状态更新" }}</strong>
        </div>
      </div>
      <div class="engine-strip-facts">
        <div>
          <span class="meta">下次扫描</span>
          <strong>{{ formatDateTime(systemStatus?.next_scan_at) }}</strong>
        </div>
        <div>
          <span class="meta">本轮到点</span>
          <strong>{{ systemStatus?.due_task_total ?? 0 }}</strong>
        </div>
        <div>
          <span class="meta">执行队列</span>
          <strong>{{ systemStatus?.queued_task_total ?? 0 }}</strong>
        </div>
      </div>
      <div class="dashboard-actions">
        <el-button type="primary" plain @click="router.push('/run')">立即执行</el-button>
        <el-button plain @click="router.push('/auto-schedule')">自动计划</el-button>
      </div>
    </section>

    <section class="panel-card dashboard-log-card">
      <div class="section-head compact-head">
        <div>
          <h2>最近异常记录</h2>
          <p class="section-subtitle">只显示失败和待人工复核的执行，完整历史在运行日志页。</p>
        </div>
        <el-button plain @click="router.push('/logs')">查看完整日志</el-button>
      </div>

      <div class="dense-list compact-log-list">
        <div v-for="log in abnormalLogs" :key="log.id" class="log-item compact-log-item">
          <div class="compact-log-head">
            <strong>{{ log.summary }}</strong>
            <el-tag size="small" :type="log.status === 'failed' ? 'danger' : 'warning'">
              {{ log.status === "failed" ? "失败" : "人工复核" }}
            </el-tag>
          </div>
          <p class="meta">{{ log.details }}</p>
          <p class="meta">{{ new Date(log.created_at).toLocaleString() }}</p>
        </div>
        <el-empty v-if="abnormalLogs.length === 0" description="当前没有异常记录" />
      </div>
    </section>
  </div>
</template>
