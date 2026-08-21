<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { RefreshRight, WarningFilled, CircleCheckFilled, UserFilled, ChatDotRound } from "@element-plus/icons-vue";

import { api } from "../api/client";
import type { DashboardSummary, SystemStatusResponse } from "../types";

const router = useRouter();
const summary = ref<DashboardSummary | null>(null);
const systemStatus = ref<SystemStatusResponse | null>(null);
const loading = ref(false);
const retrying = ref(false);
const loadError = ref("");
let pollTimer: ReturnType<typeof setInterval>;

const engineModeLabel = computed(() => {
  const mode = systemStatus.value?.mode ?? "idle";
  const labels: Record<string, string> = {
    idle: "空闲就绪",
    scanning: "扫描中",
    dispatching: "入队中",
    jitter_wait: "错峰等待",
    sending: "发送中",
    manual_review: "人工复核",
    error: "异常",
  };
  return labels[mode] ?? mode;
});

const failedCount = computed(() => summary.value?.failed_friend_total ?? 0);

const abnormalLogs = computed(() =>
  (summary.value?.latest_logs ?? []).filter(
    (log) => log.status === "failed" || log.status === "manual_review",
  ).slice(0, 6),
);

function formatDateTime(value: string | null | undefined) {
  if (!value) return "暂无";
  return new Date(value).toLocaleString();
}

async function loadDashboard() {
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
  }
}

async function handleRetryFailed() {
  retrying.value = true;
  try {
    const res = await api.retryFailedTasks();
    ElMessage.success(res.message || "已在后台启动失败任务重试");
    await loadDashboard();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "触发重试失败");
  } finally {
    retrying.value = false;
  }
}

onMounted(async () => {
  loading.value = true;
  await loadDashboard();
  loading.value = false;
  pollTimer = setInterval(loadDashboard, 4000);
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

    <!-- 失败任务快速自愈引导横幅 -->
    <div v-if="failedCount > 0" class="auto-heal-banner">
      <div class="banner-content">
        <el-icon class="banner-icon"><WarningFilled /></el-icon>
        <div>
          <strong>发现 {{ failedCount }} 位好友在上次自动续火花中遇到异常</strong>
          <p class="meta">已增强多重定位与文字表情保底机制，无需手动逐个操作，点击右侧即可一键全量恢复。</p>
        </div>
      </div>
      <el-button type="danger" :loading="retrying" :icon="RefreshRight" @click="handleRetryFailed">
        一键重试失败好友 ({{ failedCount }})
      </el-button>
    </div>

    <!-- 核心指标卡片 -->
    <section class="metrics-grid">
      <article class="metric-card metric-primary">
        <div class="metric-icon-wrap"><el-icon><UserFilled /></el-icon></div>
        <div>
          <p class="metric-label">托管账号总数</p>
          <p class="metric-value">{{ summary?.account_total ?? 0 }}</p>
        </div>
      </article>
      <article class="metric-card metric-success">
        <div class="metric-icon-wrap"><el-icon><CircleCheckFilled /></el-icon></div>
        <div>
          <p class="metric-label">正常活跃账号</p>
          <p class="metric-value">{{ summary?.healthy_account_total ?? 0 }}</p>
        </div>
      </article>
      <article class="metric-card metric-info">
        <div class="metric-icon-wrap"><el-icon><ChatDotRound /></el-icon></div>
        <div>
          <p class="metric-label">已激活续火好友</p>
          <p class="metric-value">{{ summary?.active_friend_total ?? 0 }}</p>
        </div>
      </article>
      <article class="metric-card" :class="failedCount > 0 ? 'metric-danger' : 'metric-neutral'">
        <div class="metric-icon-wrap"><el-icon><WarningFilled /></el-icon></div>
        <div>
          <p class="metric-label">异常待重试</p>
          <p class="metric-value">{{ failedCount }}</p>
        </div>
      </article>
    </section>

    <!-- 引擎实时运行状态条 -->
    <section class="panel-card engine-strip-card">
      <div class="engine-strip-main">
        <div class="engine-badge" :class="systemStatus?.mode">
          <span class="status-dot" :class="{ active: systemStatus?.is_running || systemStatus?.mode === 'scanning' }"></span>
          {{ engineModeLabel }}
        </div>
        <div class="engine-step">
          <span class="meta">实时步骤</span>
          <strong>{{ systemStatus?.current_step || systemStatus?.status_text || "系统就绪，等待扫描" }}</strong>
          <span v-if="systemStatus?.current_account && systemStatus?.current_friend" class="meta target-highlight">
            当前目标：{{ systemStatus.current_account }} ➜ {{ systemStatus.current_friend }}
          </span>
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
          <span class="meta">队列中任务</span>
          <strong>{{ systemStatus?.queued_task_total ?? 0 }}</strong>
        </div>
      </div>
      <div class="dashboard-actions">
        <el-button v-if="failedCount > 0" type="danger" plain :loading="retrying" @click="handleRetryFailed">
          重试失败 ({{ failedCount }})
        </el-button>
        <el-button type="primary" plain @click="router.push('/run')">手动执行</el-button>
        <el-button plain @click="router.push('/auto-schedule')">自动计划</el-button>
      </div>
    </section>

    <!-- 异常记录与快速排障 -->
    <section class="panel-card dashboard-log-card">
      <div class="section-head compact-head">
        <div>
          <h2>最近异常记录与自愈分析</h2>
          <p class="section-subtitle">展示最近的失败与复核事件，系统内置自动重试与文字表情保底策略。</p>
        </div>
        <div class="header-actions">
          <el-button v-if="abnormalLogs.length > 0" size="small" type="danger" plain :loading="retrying" @click="handleRetryFailed">
            一键全量重试
          </el-button>
          <el-button plain @click="router.push('/logs')">查看完整历史日志</el-button>
        </div>
      </div>

      <div class="dense-list compact-log-list">
        <div v-for="log in abnormalLogs" :key="log.id" class="log-item compact-log-item">
          <div class="compact-log-head">
            <strong>{{ log.summary }}</strong>
            <el-tag size="small" :type="log.status === 'failed' ? 'danger' : 'warning'">
              {{ log.status === "failed" ? "执行失败" : "人工复核" }}
            </el-tag>
          </div>
          <p class="meta log-details-text">{{ log.details }}</p>
          <p class="meta time-text">{{ new Date(log.created_at).toLocaleString() }}</p>
        </div>
        <el-empty v-if="abnormalLogs.length === 0" description="所有自动续火任务均运行平稳，暂无异常记录" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.auto-heal-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.08), rgba(249, 115, 22, 0.12));
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 12px;
  padding: 16px 20px;
  gap: 16px;
  margin-bottom: 8px;
}

.banner-content {
  display: flex;
  align-items: center;
  gap: 14px;
}

.banner-icon {
  font-size: 28px;
  color: var(--danger, #dc2626);
}

.banner-content p {
  margin: 4px 0 0;
}

.metric-primary { border-left: 4px solid #0f766e; }
.metric-success { border-left: 4px solid #10b981; }
.metric-info { border-left: 4px solid #3b82f6; }
.metric-danger { border-left: 4px solid #ef4444; background: rgba(239, 68, 68, 0.04); }
.metric-neutral { border-left: 4px solid #94a3b8; }

.metric-icon-wrap {
  font-size: 24px;
  color: var(--muted);
  display: flex;
  align-items: center;
  margin-right: 12px;
}

.target-highlight {
  color: var(--primary);
  font-weight: 500;
  margin-top: 2px;
}

.log-details-text {
  word-break: break-word;
}

.time-text {
  font-size: 12px;
}

@media (max-width: 768px) {
  .auto-heal-banner {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
