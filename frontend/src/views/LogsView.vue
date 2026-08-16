<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";

import AccountSelect from "../components/AccountSelect.vue";
import RunStatusTag from "../components/RunStatusTag.vue";
import { api } from "../api/client";
import type { RunLogResponse, Account } from "../types";
import { formatDateTime } from "../utils/format";

const logs = ref<RunLogResponse[]>([]);
const loading = ref(false);
const totalLogs = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);

const filterAccountId = ref<number | null>(null);
const accounts = ref<Account[]>([]);

async function loadAccounts() {
  try {
    accounts.value = await api.listAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载账号失败");
  }
}

async function loadLogs() {
  loading.value = true;
  try {
    const res = await api.listLogs(currentPage.value, pageSize.value, filterAccountId.value || undefined);
    logs.value = res.items;
    totalLogs.value = res.total;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载日志失败");
  } finally {
    loading.value = false;
  }
}

async function manualRefresh() {
  await loadLogs();
  ElMessage.success("日志列表已刷新");
}

watch([currentPage, pageSize, filterAccountId], () => {
  loadLogs();
});

onMounted(() => {
  loadAccounts();
  loadLogs();
});
</script>

<template>
  <div class="view-grid">
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>运行日志</h2>
          <p class="section-subtitle">展示每次执行的历史结果，支持按账号筛选。</p>
        </div>
        <div style="display: flex; gap: 12px; align-items: center">
          <AccountSelect
            :accounts="accounts"
            :model-value="filterAccountId"
            placeholder="全部账号"
            style="width: 200px"
            @update:model-value="filterAccountId = $event"
          />
          <el-button plain :loading="loading" @click="manualRefresh">刷新日志</el-button>
        </div>
      </div>

      <el-table :data="logs" stripe v-loading="loading" style="margin-bottom: 20px">
        <el-table-column label="执行时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>

        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <RunStatusTag :status="row.status" />
          </template>
        </el-table-column>

        <el-table-column label="概要" property="summary" width="200" />
        <el-table-column label="详细详情" property="details" min-width="300" />
      </el-table>

      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="totalLogs"
        style="justify-content: flex-end"
      />
    </section>
  </div>
</template>
