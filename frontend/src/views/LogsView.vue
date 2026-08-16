<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";

import { api } from "../api/client";
import type { RunLogResponse, Account } from "../types";

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

function statusType(status: string) {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "manual_review") return "warning";
  return "info";
}

function statusLabel(status: string) {
  if (status === "success") return "执行成功";
  if (status === "failed") return "执行失败";
  if (status === "manual_review") return "人工复核";
  return status;
}

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
          <h2>任务运行日志</h2>
          <p class="section-subtitle">展示任务的调度与执行详情，支持按账号筛选。</p>
        </div>
        <div style="display: flex; gap: 12px; align-items: center">
          <el-select v-model="filterAccountId" placeholder="全部账号" clearable style="width: 200px">
            <el-option label="-- 全部账号 --" :value="null" />
            <el-option
              v-for="acc in accounts"
              :key="acc.id"
              :label="acc.nickname"
              :value="acc.id"
            />
          </el-select>
          <el-button plain :loading="loading" @click="manualRefresh">刷新日志</el-button>
        </div>
      </div>

      <el-table :data="logs" stripe v-loading="loading" style="margin-bottom: 20px">
        <el-table-column label="执行时间" width="180">
          <template #default="{ row }">
            {{ new Date(row.created_at).toLocaleString() }}
          </template>
        </el-table-column>

        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
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
