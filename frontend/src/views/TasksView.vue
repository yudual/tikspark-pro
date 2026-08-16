<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";

import { api } from "../api/client";
import type { Account, DispatchSource, DispatchTask, RunStatus } from "../types";

const tasks = ref<DispatchTask[]>([]);
const accounts = ref<Account[]>([]);
const loading = ref(false);
const totalTasks = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);
const selectedTask = ref<DispatchTask | null>(null);
const detailVisible = ref(false);

const filterAccountId = ref<number | null>(null);
const filterStatus = ref<RunStatus | "">("");
const filterSource = ref<DispatchSource | "">("");

const statusOptions: Array<{ label: string; value: RunStatus }> = [
  { label: "等待执行", value: "pending" },
  { label: "执行中", value: "running" },
  { label: "执行成功", value: "success" },
  { label: "执行失败", value: "failed" },
  { label: "人工复核", value: "manual_review" },
  { label: "已跳过", value: "skipped" },
];

const sourceOptions: Array<{ label: string; value: DispatchSource }> = [
  { label: "手动触发", value: "manual" },
  { label: "自动计划", value: "auto" },
];

const taskStats = computed(() => {
  const rows = tasks.value;
  return {
    running: rows.filter((task) => task.status === "running").length,
    failed: rows.filter((task) => task.status === "failed").length,
    pending: rows.filter((task) => task.status === "pending").length,
  };
});

async function loadAccounts() {
  try {
    accounts.value = await api.listAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载账号失败");
  }
}

async function loadTasks() {
  loading.value = true;
  try {
    const res = await api.listTasks(
      currentPage.value,
      pageSize.value,
      filterAccountId.value || undefined,
      filterStatus.value || undefined,
      filterSource.value || undefined,
    );
    tasks.value = res.items;
    totalTasks.value = res.total;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载任务失败");
  } finally {
    loading.value = false;
  }
}

async function manualRefresh() {
  await loadTasks();
  ElMessage.success("任务列表已刷新");
}

function resetFilters() {
  filterAccountId.value = null;
  filterStatus.value = "";
  filterSource.value = "";
  currentPage.value = 1;
}

function openDetail(task: DispatchTask) {
  selectedTask.value = task;
  detailVisible.value = true;
}

function formatDateTime(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function statusType(status: RunStatus) {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "manual_review") return "warning";
  if (status === "running") return "primary";
  if (status === "skipped") return "info";
  return "";
}

function statusLabel(status: RunStatus) {
  return statusOptions.find((option) => option.value === status)?.label ?? status;
}

function sourceLabel(source: DispatchSource) {
  return sourceOptions.find((option) => option.value === source)?.label ?? source;
}

watch([currentPage, pageSize, filterAccountId, filterStatus, filterSource], () => {
  loadTasks();
});

onMounted(() => {
  loadAccounts();
  loadTasks();
});
</script>

<template>
  <div class="view-grid">
    <section class="metrics-grid">
      <article class="metric-card">
        <p class="metric-label">当前页任务</p>
        <p class="metric-value">{{ tasks.length }}</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">等待执行</p>
        <p class="metric-value">{{ taskStats.pending }}</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">执行中</p>
        <p class="metric-value">{{ taskStats.running }}</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">失败</p>
        <p class="metric-value">{{ taskStats.failed }}</p>
      </article>
    </section>

    <section class="panel-card">
      <div class="section-head task-section-head">
        <div>
          <h2>调度任务中心</h2>
          <p class="section-subtitle">查看手动触发和自动计划生成的任务状态。</p>
        </div>
        <div class="task-filters">
          <el-select v-model="filterAccountId" placeholder="全部账号" clearable>
            <el-option label="全部账号" :value="null" />
            <el-option
              v-for="acc in accounts"
              :key="acc.id"
              :label="acc.nickname"
              :value="acc.id"
            />
          </el-select>
          <el-select v-model="filterStatus" placeholder="全部状态" clearable>
            <el-option
              v-for="option in statusOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-select v-model="filterSource" placeholder="全部来源" clearable>
            <el-option
              v-for="option in sourceOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-button plain @click="resetFilters">重置</el-button>
          <el-button plain :loading="loading" @click="manualRefresh">刷新</el-button>
        </div>
      </div>

      <el-table :data="tasks" stripe v-loading="loading" class="task-table">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>

        <el-table-column label="任务目标" min-width="230">
          <template #default="{ row }">
            <div class="task-target">
              <strong>{{ row.friend_name }}</strong>
              <span>{{ row.account_name }} · {{ sourceLabel(row.source) }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="结果" min-width="260">
          <template #default="{ row }">
            <div class="task-result">
              <strong>{{ row.summary || "-" }}</strong>
              <span>{{ row.details || "-" }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="" width="90" align="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="totalTasks"
        class="task-pagination"
      />
    </section>

    <el-drawer
      v-model="detailVisible"
      title="任务详情"
      direction="rtl"
      size="420px"
    >
      <div v-if="selectedTask" class="task-detail">
        <div>
          <span class="meta">状态</span>
          <el-tag :type="statusType(selectedTask.status)">{{ statusLabel(selectedTask.status) }}</el-tag>
        </div>
        <div>
          <span class="meta">来源</span>
          <strong>{{ sourceLabel(selectedTask.source) }}</strong>
        </div>
        <div>
          <span class="meta">账号</span>
          <strong>{{ selectedTask.account_name }}</strong>
        </div>
        <div>
          <span class="meta">好友</span>
          <strong>{{ selectedTask.friend_name }}</strong>
        </div>
        <div>
          <span class="meta">计划时间</span>
          <strong>{{ formatDateTime(selectedTask.scheduled_for) }}</strong>
        </div>
        <div>
          <span class="meta">开始时间</span>
          <strong>{{ formatDateTime(selectedTask.started_at) }}</strong>
        </div>
        <div>
          <span class="meta">结束时间</span>
          <strong>{{ formatDateTime(selectedTask.finished_at) }}</strong>
        </div>
        <div>
          <span class="meta">摘要</span>
          <strong>{{ selectedTask.summary || "-" }}</strong>
        </div>
        <div>
          <span class="meta">详情</span>
          <p>{{ selectedTask.details || "-" }}</p>
        </div>
        <div>
          <span class="meta">幂等键</span>
          <code>{{ selectedTask.idempotency_key }}</code>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.task-section-head {
  align-items: flex-start;
}

.task-filters {
  display: grid;
  grid-template-columns: 180px 150px 150px auto auto;
  gap: 10px;
  align-items: center;
}

.task-table {
  width: 100%;
  margin-bottom: 18px;
}

.task-target,
.task-result {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.task-target span,
.task-result span {
  color: var(--muted);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-result strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-pagination {
  justify-content: flex-end;
}

.task-detail {
  display: grid;
  gap: 16px;
}

.task-detail > div {
  display: grid;
  gap: 6px;
}

.task-detail p {
  margin: 0;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.task-detail code {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--muted);
}

@media (max-width: 980px) {
  .task-section-head {
    display: grid;
  }

  .task-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .task-filters {
    grid-template-columns: 1fr;
  }
}
</style>
