<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import AccountSelect from "../components/AccountSelect.vue";
import RunStatusTag from "../components/RunStatusTag.vue";
import { api } from "../api/client";
import type { Account, DispatchSource, DispatchTask, Friend, RunStatus } from "../types";
import { formatDateTime } from "../utils/format";

type FriendOption = Friend & {
  account_name: string;
};

const accounts = ref<Account[]>([]);
const friends = ref<FriendOption[]>([]);
const loading = ref(false);
const friendLoading = ref(false);
const running = ref(false);
const selectedAccountId = ref<number | null>(null);
const selectedFriendId = ref<number | null>(null);

const selectedAccount = computed(() =>
  accounts.value.find((account) => account.id === selectedAccountId.value) ?? null,
);

const selectedFriend = computed(() =>
  friends.value.find((friend) => friend.id === selectedFriendId.value) ?? null,
);

const friendPlaceholder = computed(() =>
  selectedAccountId.value ? "当前账号的全部启用好友" : "全部账号的全部启用好友",
);

const runTargetText = computed(() => {
  if (selectedFriend.value) {
    return `${selectedFriend.value.account_name} -> ${selectedFriend.value.friend_nickname}`;
  }
  if (selectedAccount.value) {
    return `${selectedAccount.value.nickname} 的全部启用好友`;
  }
  return "全部账号的全部启用好友";
});

async function loadAccounts() {
  loading.value = true;
  try {
    accounts.value = await api.listAccounts();
    await loadFriends(selectedAccountId.value);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载账号失败");
  } finally {
    loading.value = false;
  }
}

async function loadFriends(accountId: number | null) {
  selectedFriendId.value = null;
  friends.value = [];
  friendLoading.value = true;
  try {
    const targetAccounts = accountId
      ? accounts.value.filter((account) => account.id === accountId)
      : accounts.value;
    const friendGroups = await Promise.all(
      targetAccounts.map(async (account) => {
        const items = await api.listFriends(account.id);
        return items
          .filter((friend) => friend.is_active)
          .map((friend) => ({ ...friend, account_name: account.nickname }));
      }),
    );
    friends.value = friendGroups.flat();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载好友失败");
  } finally {
    friendLoading.value = false;
  }
}

async function onAccountChange(value: number | null) {
  selectedAccountId.value = value;
  await loadFriends(value);
}

async function runManualTask() {
  try {
    await ElMessageBox.confirm(
      `确认立即执行：${runTargetText.value}？`,
      "手动执行确认",
      {
        type: "warning",
        confirmButtonText: "确认执行",
        cancelButtonText: "取消",
      },
    );
  } catch {
    return;
  }

  running.value = true;
  try {
    await api.runTasks(
      selectedAccountId.value ?? undefined,
      selectedFriendId.value ?? undefined,
      false,
    );
    ElMessage.success("已创建执行任务，任务会显示在下方列表");
    await loadTasks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "手动执行失败");
  } finally {
    running.value = false;
  }
}

const tasks = ref<DispatchTask[]>([]);
const loadingTasks = ref(false);
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

async function loadTasks() {
  loadingTasks.value = true;
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
    loadingTasks.value = false;
  }
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
    <section class="panel-card manual-run-card" v-loading="loading">
      <div class="section-head">
        <div>
          <h2>手动执行</h2>
          <p class="section-subtitle">选择执行范围后立即触发，任务会出现在下方任务列表中。</p>
        </div>
      </div>

      <div class="manual-run-grid">
        <label class="strategy-field">
          <span class="meta">执行账号</span>
          <AccountSelect
            :accounts="accounts"
            :model-value="selectedAccountId"
            placeholder="全部账号"
            @update:model-value="onAccountChange"
          />
        </label>

        <label class="strategy-field">
          <span class="meta">执行好友</span>
          <el-select
            v-model="selectedFriendId"
            :loading="friendLoading"
            clearable
            filterable
            :placeholder="friendPlaceholder"
          >
            <el-option label="全部启用好友" :value="null" />
            <el-option
              v-for="friend in friends"
              :key="friend.id"
              :label="`${friend.account_name} / ${friend.friend_nickname}`"
              :value="friend.id"
            />
          </el-select>
        </label>
      </div>

      <div class="manual-run-preview">
        <span class="meta">即将执行</span>
        <strong>{{ runTargetText }}</strong>
      </div>

      <div class="manual-run-actions">
        <el-button type="success" :loading="running" @click="runManualTask">立即执行</el-button>
        <el-button plain :loading="loading" @click="loadAccounts">刷新账号</el-button>
      </div>
    </section>

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
          <h2>任务列表</h2>
          <p class="section-subtitle">查看手动触发和自动计划生成的任务状态。</p>
        </div>
        <div class="task-filters">
          <AccountSelect
            :accounts="accounts"
            :model-value="filterAccountId"
            placeholder="全部账号"
            @update:model-value="filterAccountId = $event"
          />
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
          <el-button plain :loading="loadingTasks" @click="loadTasks">刷新</el-button>
        </div>
      </div>

      <el-table :data="tasks" stripe v-loading="loadingTasks" class="task-table">
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
            <RunStatusTag :status="row.status" />
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
          <RunStatusTag :status="selectedTask.status" />
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
