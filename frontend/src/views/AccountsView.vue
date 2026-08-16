<script setup lang="ts">
import { computed, onMounted, ref, reactive } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { api } from "../api/client";
import type { Account, Friend } from "../types";

const accounts = ref<Account[]>([]);
const loading = ref(false);
const refreshingAccount = reactive<Record<number, boolean>>({});
const importDialogVisible = ref(false);
const importing = ref(false);
const cookieText = ref("");
const cookieDialogVisible = ref(false);
const updatingCookie = ref(false);
const cookieUpdateText = ref("");
const cookieUpdateAccount = ref<Account | null>(null);

const activeTab = ref("all");
const searchQuery = ref("");

const filteredAccounts = computed(() => {
  return accounts.value.filter(acc => {
    const matchesTab = activeTab.value === "all" || acc.status === activeTab.value;
    const matchesSearch = !searchQuery.value || 
      acc.nickname.toLowerCase().includes(searchQuery.value.toLowerCase()) || 
      acc.dy_id.toLowerCase().includes(searchQuery.value.toLowerCase());
    return matchesTab && matchesSearch;
  });
});

const editDialogVisible = ref(false);
const editForm = ref({
  id: 0,
  nickname: "",
  avatar_url: "",
  proxy_url: "",
});

const friendDialogVisible = ref(false);
const currentAccount = ref<Account | null>(null);
const currentFriends = ref<Friend[]>([]);
const friendLoading = ref(false);

const activeTotalText = computed(() => {
  if (!currentAccount.value) return "";
  return `已激活 ${currentAccount.value.active_friend_count}/${currentAccount.value.friend_count} 个好友`;
});

function formatScheduleTime(value: string | null) {
  if (!value) return "待生成";
  return new Date(value).toLocaleString();
}

function statusLabel(status: Account["status"]) {
  if (status === "healthy") return "托管中";
  if (status === "invalid") return "凭证失效";
  return "待确认";
}

function formatCookieDate(value: string | null) {
  if (!value) return "未知";
  return new Date(value).toLocaleString();
}

function cookieStatusLabel(account: Account) {
  if (!account.cookie_expires_at) return "Cookie 过期时间未知";
  const diffMs = new Date(account.cookie_expires_at).getTime() - Date.now();
  if (diffMs <= 0) return "Cookie 已过期，请更新";
  const days = Math.floor(diffMs / 86400000);
  if (days <= 1) return "Cookie 即将过期";
  return `Cookie 约 ${days} 天后过期`;
}

function cookieStatusClass(account: Account) {
  if (!account.cookie_expires_at) return "unknown";
  const diffMs = new Date(account.cookie_expires_at).getTime() - Date.now();
  if (diffMs <= 0) return "expired";
  if (diffMs <= 2 * 86400000) return "warning";
  return "healthy";
}

async function loadAccounts() {
  loading.value = true;
  try {
    accounts.value = await api.listAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

async function manualRefresh() {
  await loadAccounts();
  ElMessage.success("账号列表已刷新");
}

async function handleRefreshAccount(account: Account) {
  refreshingAccount[account.id] = true;
  try {
    await api.refreshFriends(account.id);
    await loadAccounts();
    ElMessage.success(account.avatar_url ? "账号资料已刷新" : "已重新尝试获取账号头像和好友资料");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "刷新账号资料失败");
  } finally {
    refreshingAccount[account.id] = false;
  }
}


async function submitImport() {
  if (!cookieText.value.trim()) {
    ElMessage.warning("请先粘贴 Cookie 凭证");
    return;
  }
  importing.value = true;
  try {
    await api.importAccount(cookieText.value.trim());
    ElMessage.success("账号已导入");
    cookieText.value = "";
    importDialogVisible.value = false;
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "导入失败");
  } finally {
    importing.value = false;
  }
}

function openCookieDialog(account: Account) {
  cookieUpdateAccount.value = account;
  cookieUpdateText.value = "";
  cookieDialogVisible.value = true;
}

async function submitCookieUpdate() {
  if (!cookieUpdateAccount.value) return;
  if (!cookieUpdateText.value.trim()) {
    ElMessage.warning("请先粘贴新的 Cookie");
    return;
  }
  updatingCookie.value = true;
  try {
    await api.updateAccountCookie(cookieUpdateAccount.value.id, cookieUpdateText.value.trim());
    ElMessage.success("Cookie 已更新，并已重新同步账号资料");
    cookieDialogVisible.value = false;
    cookieUpdateText.value = "";
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新 Cookie 失败");
  } finally {
    updatingCookie.value = false;
  }
}

function openEditDialog(account: Account) {
  editForm.value = {
    id: account.id,
    nickname: account.nickname,
    avatar_url: account.avatar_url || "",
    proxy_url: account.proxy_url || "",
  };
  editDialogVisible.value = true;
}

async function submitUpdate() {
  try {
    await api.updateAccount(editForm.value.id, {
      nickname: editForm.value.nickname,
      avatar_url: editForm.value.avatar_url,
      proxy_url: editForm.value.proxy_url,
    });
    ElMessage.success("账号已更新");
    editDialogVisible.value = false;
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新失败");
  }
}

async function handleRemoveAccount(account: Account) {
  try {
    await ElMessageBox.confirm(
      `确定要删除账号 ${account.nickname} 吗？此操作将同时移除其所有好友关系和消息配置。`,
      "警告",
      {
        confirmButtonText: "确定删除",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
    await api.deleteAccount(account.id);
    ElMessage.success("账号已移除");
    await loadAccounts();
  } catch (error) {
    if (error !== "cancel") {
      ElMessage.error(error instanceof Error ? error.message : "删除失败");
    }
  }
}

async function openFriendDialog(account: Account) {
  currentAccount.value = account;
  friendDialogVisible.value = true;
  await loadFriends(account.id);
}

async function loadFriends(accountId: number) {
  friendLoading.value = true;
  try {
    currentFriends.value = await api.listFriends(accountId);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载好友失败");
  } finally {
    friendLoading.value = false;
  }
}

async function refreshFriends() {
  if (!currentAccount.value) return;
  friendLoading.value = true;
  try {
    currentFriends.value = await api.refreshFriends(currentAccount.value.id);
    ElMessage.success("好友列表已刷新");
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "刷新失败");
  } finally {
    friendLoading.value = false;
  }
}

async function toggleFriend(friend: Friend, value: boolean) {
  try {
    const updated = await api.toggleFriend(friend.id, value);
    const index = currentFriends.value.findIndex((item) => item.id === friend.id);
    if (index >= 0) currentFriends.value[index] = updated;
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新失败");
    friend.is_active = !value;
  }
}

onMounted(loadAccounts);
</script>

<template>
  <div class="view-grid">
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>账号资产管理</h2>
          <p class="section-subtitle">支持导入凭证、查看托管状态、批量管理好友开关。</p>
        </div>
        <div style="display: flex; gap: 12px">
          <el-button type="primary" @click="importDialogVisible = true">导入新账号凭证</el-button>
          <el-button plain :loading="loading" @click="manualRefresh">刷新列表</el-button>
        </div>
      </div>

      <div class="filters-bar">
        <el-tabs v-model="activeTab" class="custom-tabs">
          <el-tab-pane label="全部账号" name="all" />
          <el-tab-pane label="健康托管" name="healthy" />
          <el-tab-pane label="待确认" name="unknown" />
          <el-tab-pane label="凭证失效" name="invalid" />
        </el-tabs>
        <el-input
          v-model="searchQuery"
          placeholder="搜索昵称或抖音号"
          clearable
          style="width: 240px"
        />
      </div>

      <div class="account-grid" v-loading="loading">
        <article v-for="account in filteredAccounts" :key="account.id" class="account-card">
          <div class="account-head">
            <el-avatar
              :size="56"
              :src="account.avatar_url"
              class="avatar account-avatar"
              :class="{ missing: !account.avatar_url }"
            >
              <span>{{ account.nickname.charAt(0) }}</span>
            </el-avatar>
            <div style="min-width: 0; flex: 1">
              <strong class="account-name">{{ account.nickname }}</strong>
              <div class="meta mono dy-id-text" :title="account.dy_id">{{ account.dy_id }}</div>
            </div>
          </div>

          <div class="status-pill" :class="account.status">
            <span>{{ statusLabel(account.status) }}</span>
          </div>

          <div class="account-info">
            <div class="meta">已联络 {{ account.active_friend_count }}/{{ account.friend_count }} 个好友</div>
            <div class="cookie-status" :class="cookieStatusClass(account)">
              {{ cookieStatusLabel(account) }}
            </div>
            <div class="meta">Cookie 更新：{{ formatCookieDate(account.cookie_updated_at) }}</div>
            <div class="meta truncate" v-if="account.proxy_url" :title="account.proxy_url">
              代理: {{ account.proxy_url }}
            </div>
            <div class="meta status-reason">{{ account.status_reason }}</div>
          </div>

          <div class="account-actions">
            <el-button type="primary" plain @click="openFriendDialog(account)">管理好友</el-button>
            <el-button plain :loading="refreshingAccount[account.id]" @click="handleRefreshAccount(account)">刷新资料</el-button>
            <el-button plain @click="openCookieDialog(account)">更新 Cookie</el-button>
            <el-button plain @click="openEditDialog(account)">编辑</el-button>
            <el-button type="danger" plain @click="handleRemoveAccount(account)">删除</el-button>
          </div>
        </article>
      </div>
    </section>

    <el-dialog v-model="importDialogVisible" title="导入账号凭证" width="640px">
      <el-input
        v-model="cookieText"
        type="textarea"
        :rows="8"
        placeholder="请粘贴完整 Cookie 凭证字符串"
      />
      <template #footer>
        <el-button @click="importDialogVisible = false" :disabled="importing">取消</el-button>
        <el-button type="primary" @click="submitImport" :loading="importing">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="cookieDialogVisible" title="更新账号 Cookie" width="640px">
      <p class="meta" style="margin-top: 0">
        当前账号：{{ cookieUpdateAccount?.nickname }}。粘贴新的 Cookie 后，会保留原有好友、消息和计划配置，并重新同步账号资料。
      </p>
      <el-input
        v-model="cookieUpdateText"
        type="textarea"
        :rows="8"
        placeholder="请粘贴新的完整 Cookie 凭证"
      />
      <template #footer>
        <el-button @click="cookieDialogVisible = false" :disabled="updatingCookie">取消</el-button>
        <el-button type="primary" @click="submitCookieUpdate" :loading="updatingCookie">更新 Cookie</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" title="编辑账号配置" width="480px">
      <el-form label-position="top">
        <el-form-item label="账号备注昵称">
          <el-input v-model="editForm.nickname" placeholder="给账号起个好记的名字" />
        </el-form-item>
        <el-form-item label="头像 URL (可选)">
          <el-input v-model="editForm.avatar_url" placeholder="自动获取失败时，可以手动粘贴头像图片地址" />
          <p class="meta" style="margin-top: 4px">刷新好友列表会再次尝试自动获取；如果抖音页面没有暴露头像，可以在这里手动补充。</p>
        </el-form-item>
        <el-form-item label="独立代理 URL (可选)">
          <el-input v-model="editForm.proxy_url" placeholder="例如 http://user:pass@host:port" />
          <p class="meta" style="margin-top: 4px">留空则使用服务器直连。配置代理可有效降低风控风险。</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitUpdate">保存修改</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="friendDialogVisible"
      :title="currentAccount ? `${currentAccount.nickname} · 好友管理` : '好友管理'"
      width="720px"
    >
      <div class="section-head" style="margin-bottom: 8px">
        <div class="meta">{{ activeTotalText }}</div>
        <el-button plain @click="refreshFriends">刷新好友列表</el-button>
      </div>

      <div v-loading="friendLoading">
        <div v-for="friend in currentFriends" :key="friend.id" class="friend-row">
          <img :src="friend.friend_avatar" alt="" class="avatar" style="width: 48px; height: 48px" />
          <div style="min-width: 0">
            <strong>{{ friend.friend_nickname }}</strong>
            <div class="meta mono">{{ friend.friend_dy_id }}</div>
            <div v-if="friend.is_active" class="meta">
              自动续火时段 {{ friend.schedule_window }} · 下次执行 {{ formatScheduleTime(friend.next_run_at) }}
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 12px">
            <el-switch
              :model-value="friend.is_active"
              @update:model-value="(value: boolean) => toggleFriend(friend, value)"
            />
          </div>
        </div>
        <el-empty v-if="currentFriends.length === 0" description="暂无好友数据" />
      </div>
    </el-dialog>
  </div>
</template>
