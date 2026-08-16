<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { api } from "../api/client";
import type { Account, Friend } from "../types";

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
    ElMessage.success("已创建手动执行任务，请到任务中心查看进度");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "手动执行失败");
  } finally {
    running.value = false;
  }
}

onMounted(loadAccounts);
</script>

<template>
  <div class="view-grid">
    <section class="panel-card manual-run-card" v-loading="loading">
      <div class="section-head">
        <div>
          <h2>手动执行</h2>
          <p class="section-subtitle">所有立即执行入口统一放在这里，避免在账号、消息配置页面误触。</p>
        </div>
      </div>

      <div class="manual-run-grid">
        <label class="strategy-field">
          <span class="meta">执行账号</span>
          <el-select
            :model-value="selectedAccountId"
            clearable
            placeholder="全部账号"
            @update:model-value="onAccountChange"
          >
            <el-option label="全部账号" :value="null" />
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="account.nickname"
              :value="account.id"
            />
          </el-select>
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
  </div>
</template>
