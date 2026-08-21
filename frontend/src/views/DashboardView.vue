<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  RefreshRight,
  WarningFilled,
  CircleCheckFilled,
  UserFilled,
  ChatDotRound,
  VideoPlay,
  Calendar,
  ArrowRight,
  Document,
} from "@element-plus/icons-vue";

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
  ).slice(0, 5),
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
    ElMessage.success(res.message || "已启动失败任务重试");
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
  <div class="view-grid" v-loading="loading">
    <el-alert
      v-if="loadError"
      class="dashboard-alert"
      :title="loadError"
      type="warning"
      show-icon
      :closable="false"
    />

    <!-- 异常快速自愈引导横幅 -->
    <div v-if="failedCount > 0" class="auto-heal-banner">
      <div class="banner-left">
        <div class="banner-icon-box">
          <el-icon><WarningFilled /></el-icon>
        </div>
        <div class="banner-text">
          <strong>检测到 {{ failedCount }} 位好友上次续火花存在异常</strong>
          <p>已启用五级智能重试与文字表情保底机制，点击右侧即可一键全量恢复派发。</p>
        </div>
      </div>
      <el-button type="danger" :loading="retrying" :icon="RefreshRight" size="large" @click="handleRetryFailed">
        一键重试失败好友 ({{ failedCount }})
      </el-button>
    </div>

    <!-- 核心指标卡片 -->
    <section class="metrics-grid">
      <article class="metric-card metric-primary">
        <div class="metric-icon-wrap">
          <el-icon><UserFilled /></el-icon>
        </div>
        <div class="metric-info-content">
          <p class="metric-label">托管账号总数</p>
          <p class="metric-value">{{ summary?.account_total ?? 0 }}</p>
        </div>
      </article>

      <article class="metric-card metric-success">
        <div class="metric-icon-wrap">
          <el-icon><CircleCheckFilled /></el-icon>
        </div>
        <div class="metric-info-content">
          <p class="metric-label">正常托管账号</p>
          <p class="metric-value">{{ summary?.healthy_account_total ?? 0 }}</p>
        </div>
      </article>

      <article class="metric-card metric-info">
        <div class="metric-icon-wrap">
          <el-icon><ChatDotRound /></el-icon>
        </div>
        <div class="metric-info-content">
          <p class="metric-label">已激活续火好友</p>
          <p class="metric-value">{{ summary?.active_friend_total ?? 0 }}</p>
        </div>
      </article>

      <article class="metric-card" :class="failedCount > 0 ? 'metric-danger' : 'metric-neutral'">
        <div class="metric-icon-wrap">
          <el-icon><WarningFilled /></el-icon>
        </div>
        <div class="metric-info-content">
          <p class="metric-label">异常待处理</p>
          <p class="metric-value">{{ failedCount }}</p>
        </div>
      </article>
    </section>

    <!-- 引擎实时监控面板 -->
    <section class="panel-card engine-strip-card">
      <div class="engine-strip-top">
        <div class="engine-strip-main">
          <div class="engine-badge" :class="systemStatus?.mode">
            <span class="status-dot" :class="{ active: systemStatus?.is_running || systemStatus?.mode === 'scanning' }"></span>
            {{ engineModeLabel }}
          </div>
          <div class="engine-step">
            <span class="meta">当前执行步骤</span>
            <strong>{{ systemStatus?.current_step || systemStatus?.status_text || "调度器就绪中" }}</strong>
          </div>
        </div>
        <div class="engine-actions">
          <el-button v-if="failedCount > 0" type="danger" plain :loading="retrying" :icon="RefreshRight" @click="handleRetryFailed">
            重试失败 ({{ failedCount }})
          </el-button>
          <el-button type="primary" :icon="VideoPlay" @click="router.push('/run')">手动执行</el-button>
          <el-button plain :icon="Calendar" @click="router.push('/auto-schedule')">自动计划</el-button>
        </div>
      </div>

      <div class="engine-strip-facts">
        <div class="engine-fact-box">
          <span class="meta">下次定时扫描</span>
          <strong>{{ formatDateTime(systemStatus?.next_scan_at) }}</strong>
        </div>
        <div class="engine-fact-box">
          <span class="meta">本轮到点任务</span>
          <strong>{{ systemStatus?.due_task_total ?? 0 }} 个</strong>
        </div>
        <div class="engine-fact-box">
          <span class="meta">执行队列排队</span>
          <strong>{{ systemStatus?.queued_task_total ?? 0 }} 个</strong>
        </div>
        <div class="engine-fact-box" v-if="systemStatus?.current_account && systemStatus?.current_friend">
          <span class="meta">当前派发目标</span>
          <strong style="color: var(--primary)">{{ systemStatus.current_account }} ➜ {{ systemStatus.current_friend }}</strong>
        </div>
      </div>
    </section>

    <!-- 异常记录与排障分析 -->
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>最近异常记录与自愈分析</h2>
          <p class="section-subtitle">展示最近执行中的失败事件，系统已内置自动文字表情降级与多级寻人重试策略。</p>
        </div>
        <el-button plain :icon="Document" @click="router.push('/logs')">
          查看完整运行日志 <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>

      <div class="abnormal-list">
        <div v-for="log in abnormalLogs" :key="log.id" class="abnormal-item">
          <div class="abnormal-head">
            <div class="abnormal-title">
              <span class="abnormal-dot"></span>
              <strong>{{ log.summary }}</strong>
            </div>
            <div class="abnormal-tags">
              <el-tag size="small" :type="log.status === 'failed' ? 'danger' : 'warning'" effect="light">
                {{ log.status === "failed" ? "执行失败" : "人工复核" }}
              </el-tag>
              <span class="meta time-text">{{ new Date(log.created_at).toLocaleString() }}</span>
            </div>
          </div>
          <p class="abnormal-detail">{{ log.details }}</p>
        </div>

        <el-empty
          v-if="abnormalLogs.length === 0"
          description="太棒了！近期所有好友自动续火花任务均平稳执行完成"
          :image-size="80"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.auto-heal-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.06) 0%, rgba(249, 115, 22, 0.08) 100%);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: var(--radius-lg);
  padding: 18px 24px;
  gap: 20px;
}

.banner-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.banner-icon-box {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
}

.banner-text strong {
  font-size: 15px;
  color: #991b1b;
  display: block;
}

.banner-text p {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}

.engine-actions {
  display: flex;
  gap: 10px;
}

.abnormal-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.abnormal-item {
  background: #f8fafc;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.15s ease;
}

.abnormal-item:hover {
  border-color: #cbd5e1;
  background: #ffffff;
}

.abnormal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.abnormal-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.abnormal-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--danger);
}

.abnormal-tags {
  display: flex;
  align-items: center;
  gap: 10px;
}

.abnormal-detail {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.5;
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
