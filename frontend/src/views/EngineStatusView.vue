<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";

import { api } from "../api/client";
import type { SystemStatusResponse } from "../types";

const systemStatus = ref<SystemStatusResponse | null>(null);
const loading = ref(false);
const loadError = ref("");
let hasShownLoadError = false;
let pollTimer: ReturnType<typeof setInterval>;
let clockTimer: ReturnType<typeof setInterval>;
const nowMs = ref(Date.now());

const engineModeLabel = computed(() => {
  const mode = systemStatus.value?.mode ?? "idle";
  const labels: Record<string, string> = {
    idle: "扫描待命中",
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

function formatDurationMs(durationMs: number | null | undefined) {
  const ms = Math.max(0, durationMs ?? 0);
  if (ms < 1000) return `${ms} ms`;
  const totalSeconds = Math.floor(ms / 1000);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes <= 0) return `${seconds} 秒`;
  return `${minutes} 分 ${seconds} 秒`;
}

function formatSeconds(totalSeconds: number) {
  if (totalSeconds <= 0) return "0 秒";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes <= 0) return `${seconds} 秒`;
  return `${minutes} 分 ${seconds} 秒`;
}

const nextScanCountdown = computed(() => {
  const nextScanAt = systemStatus.value?.next_scan_at;
  if (!nextScanAt) return "暂无";
  const diff = Math.max(0, Math.ceil((new Date(nextScanAt).getTime() - nowMs.value) / 1000));
  return formatSeconds(diff);
});

const lastScanAgo = computed(() => {
  const lastScanAt = systemStatus.value?.last_scan_at;
  if (!lastScanAt) return "暂无";
  const diff = Math.max(0, Math.floor((nowMs.value - new Date(lastScanAt).getTime()) / 1000));
  return `${formatSeconds(diff)}前`;
});

const heartbeatText = computed(() => {
  const lastScanAt = systemStatus.value?.last_scan_at;
  const nextScanAt = systemStatus.value?.next_scan_at;
  if (!lastScanAt || !nextScanAt) return "等待首次扫描";
  const intervalSeconds = Math.max(
    1,
    Math.round((new Date(nextScanAt).getTime() - new Date(lastScanAt).getTime()) / 1000),
  );
  const elapsedSeconds = Math.max(0, Math.floor((nowMs.value - new Date(lastScanAt).getTime()) / 1000));
  if (elapsedSeconds <= intervalSeconds + 5) return "扫描心跳正常";
  if (elapsedSeconds <= intervalSeconds * 2) return "扫描稍有延迟";
  return "扫描可能异常";
});

const waitCountdown = computed(() => {
  const seconds = systemStatus.value?.current_wait_seconds ?? 0;
  return seconds > 0 ? formatSeconds(seconds) : "暂无等待";
});

const retryRemainingLabel = computed(() => {
  const count = systemStatus.value?.retry_remaining ?? 0;
  return count > 0 ? `${count} 次` : "暂无重试";
});

const blockPointLabel = computed(() => {
  return systemStatus.value?.blocked_point || "当前无阻塞";
});

async function loadSystemStatus(showLoading = false) {
  if (showLoading) loading.value = true;
  try {
    systemStatus.value = await api.getSystemStatus();
    loadError.value = "";
    hasShownLoadError = false;
  } catch (error) {
    const message = error instanceof Error ? error.message : "加载调度状态失败";
    loadError.value = message;
    if (!hasShownLoadError) {
      ElMessage.error(message);
      hasShownLoadError = true;
    }
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadSystemStatus(true);
  pollTimer = setInterval(() => loadSystemStatus(), 2000);
  clockTimer = setInterval(() => {
    nowMs.value = Date.now();
  }, 1000);
});

onUnmounted(() => {
  clearInterval(pollTimer);
  clearInterval(clockTimer);
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

    <section v-if="systemStatus" class="panel-card engine-card">
      <div class="section-head">
        <div>
          <h2>调度引擎状态</h2>
          <p class="section-subtitle">这里实时显示自动扫描、错峰等待、浏览器发送与异常状态。</p>
        </div>
        <div class="engine-badge" :class="systemStatus.mode">
          <span class="status-dot" :class="{ active: systemStatus.is_running || systemStatus.mode === 'scanning' }"></span>
          {{ engineModeLabel }}
        </div>
      </div>

      <div class="engine-grid">
        <div class="engine-primary">
          <div class="meta">当前步骤</div>
          <strong>{{ systemStatus.current_step || systemStatus.status_text }}</strong>
          <p class="meta" style="margin: 8px 0 0">{{ systemStatus.status_text }}</p>
        </div>
        <div class="engine-stat">
          <span class="meta">执行进度</span>
          <strong>{{ systemStatus.completed_tasks }} / {{ systemStatus.total_tasks }}</strong>
        </div>
        <div class="engine-stat">
          <span class="meta">本轮到点任务</span>
          <strong>{{ systemStatus.due_task_total }}</strong>
        </div>
        <div class="engine-stat">
          <span class="meta">自动续火池</span>
          <strong>{{ systemStatus.queued_task_total }}</strong>
        </div>
      </div>

      <div class="status-detail-grid engine-detail-grid">
        <div>
          <span class="meta">本轮扫描耗时</span>
          <strong>{{ formatDurationMs(systemStatus.last_scan_duration_ms) }}</strong>
        </div>
        <div>
          <span class="meta">当前等待倒计时</span>
          <strong>{{ waitCountdown }}</strong>
        </div>
        <div>
          <span class="meta">最近成功发送</span>
          <strong>{{ formatDateTime(systemStatus.last_success_at) }}</strong>
          <span class="meta">{{ systemStatus.last_success_target || systemStatus.last_success_summary || "暂无" }}</span>
        </div>
        <div>
          <span class="meta">最近失败原因</span>
          <strong>{{ formatDateTime(systemStatus.last_failure_at) }}</strong>
          <span class="meta">{{ systemStatus.last_failure_reason || "暂无失败记录" }}</span>
        </div>
        <div>
          <span class="meta">重试剩余次数</span>
          <strong>{{ retryRemainingLabel }}</strong>
        </div>
        <div>
          <span class="meta">当前阻塞点</span>
          <strong>{{ blockPointLabel }}</strong>
        </div>
      </div>

      <div class="status-detail-grid">
        <div>
          <span class="meta">扫描心跳</span>
          <strong>{{ heartbeatText }}</strong>
        </div>
        <div>
          <span class="meta">下次扫描倒计时</span>
          <strong>{{ nextScanCountdown }}</strong>
        </div>
        <div>
          <span class="meta">当前账号</span>
          <strong>{{ systemStatus.current_account || "暂无" }}</strong>
        </div>
        <div>
          <span class="meta">当前好友</span>
          <strong>{{ systemStatus.current_friend || "暂无" }}</strong>
        </div>
        <div>
          <span class="meta">上次扫描</span>
          <strong>{{ formatDateTime(systemStatus.last_scan_at) }}</strong>
          <span class="meta">{{ lastScanAgo }}</span>
        </div>
        <div>
          <span class="meta">下次扫描</span>
          <strong>{{ formatDateTime(systemStatus.next_scan_at) }}</strong>
        </div>
      </div>

      <div v-if="systemStatus.last_error" class="engine-error">
        {{ systemStatus.last_error }}
      </div>
    </section>
  </div>
</template>
