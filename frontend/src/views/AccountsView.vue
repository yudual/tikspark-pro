<script setup lang="ts">
import { computed, onMounted, ref, reactive } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus, Refresh, Key, Edit, Delete, Search, UserFilled, CircleCheck, Check, Close } from "@element-plus/icons-vue";

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
const friendSearchQuery = ref("");

const filteredAccounts = computed(() => {
  return accounts.value.filter((acc) => {
    const matchesTab = activeTab.value === "all" || acc.status === activeTab.value;
    const matchesSearch =
      !searchQuery.value ||
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
const togglingAll = ref(false);

const filteredFriends = computed(() => {
  if (!friendSearchQuery.value.trim()) return currentFriends.value;
  const q = friendSearchQuery.value.toLowerCase();
  return currentFriends.value.filter(
    (f) => f.friend_nickname.toLowerCase().includes(q) || f.friend_dy_id.toLowerCase().includes(q),
  );
});

const activeTotalText = computed(() => {
  if (!currentAccount.value) return "";
  return `已激活 ${currentAccount.value.active_friend_count} / ${currentAccount.value.friend_count} 位好友`;
});

function formatScheduleTime(value: string | null) {
  if (!value) return "待生成";
  return new Date(value).toLocaleString();
}

function statusLabel(status: Account["status"]) {
  if (status === "healthy") return "正常托管中";
  if (status === "invalid") return "Cookie 已失效";
  return "待确认";
}

function formatCookieDate(value: string | null) {
  if (!value) return "未知";
  return new Date(value).toLocaleString();
}

function cookieStatusLabel(account: Account) {
  if (!account.cookie_expires_at) return "Cookie 状态良好";
  const diffMs = new Date(account.cookie_expires_at).getTime() - Date.now();
  if (diffMs <= 0) return "Cookie 已过期";
  const days = Math.floor(diffMs / 86400000);
  if (days <= 1) return "Cookie 即将过期";
  return `Cookie 约 ${days} 天后过期`;
}

function cookieStatusClass(account: Account) {
  if (account.status === "invalid") return "expired";
  if (!account.cookie_expires_at) return "healthy";
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
    ElMessage.success(account.avatar_url ? "账号与好友列表已更新" : "已重新同步资料");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "同步账号资料失败");
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
    ElMessage.success("账号已成功导入并同步好友");
    cookieText.value = "";
    importDialogVisible.value = false;
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "导入失败，请检查 Cookie 完整性");
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
    ElMessage.success("Cookie 已更新并保留原有配置");
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
    ElMessage.success("账号信息已更新");
    editDialogVisible.value = false;
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新失败");
  }
}

async function handleRemoveAccount(account: Account) {
  try {
    await ElMessageBox.confirm(
      `确定要删除账号【${account.nickname}】吗？此操作将同时移除其所有好友关系和消息配置。`,
      "操作确认",
      {
        confirmButtonText: "确定删除",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
    await api.deleteAccount(account.id);
    ElMessage.success("账号已安全移除");
    await loadAccounts();
  } catch (error) {
    if (error !== "cancel") {
      ElMessage.error(error instanceof Error ? error.message : "删除失败");
    }
  }
}

async function openFriendDialog(account: Account) {
  currentAccount.value = account;
  friendSearchQuery.value = "";
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

async function batchToggleFriends(enable: boolean) {
  if (!currentFriends.value.length) return;
  togglingAll.value = true;
  try {
    for (const friend of currentFriends.value) {
      if (friend.is_active !== enable) {
        const updated = await api.toggleFriend(friend.id, enable);
        const index = currentFriends.value.findIndex((item) => item.id === friend.id);
        if (index >= 0) currentFriends.value[index] = updated;
      }
    }
    await loadAccounts();
    ElMessage.success(enable ? "已全部激活" : "已全部关闭");
  } catch (error) {
    ElMessage.error("批量切换失败");
  } finally {
    togglingAll.value = false;
  }
}

onMounted(loadAccounts);
</script>

<template>
  <div class="view-grid">
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>账号资产与凭证管理</h2>
          <p class="section-subtitle">Cookie 凭证本地加密安全托管，自动执行时支持真人拟态与无感保活。</p>
        </div>
        <div style="display: flex; gap: 10px">
          <el-button type="primary" :icon="Plus" @click="importDialogVisible = true">导入新账号</el-button>
          <el-button plain :icon="Refresh" :loading="loading" @click="manualRefresh">刷新列表</el-button>
        </div>
      </div>

      <div class="filters-bar">
        <el-tabs v-model="activeTab" class="custom-tabs">
          <el-tab-pane label="全部账号" name="all" />
          <el-tab-pane label="正常托管" name="healthy" />
          <el-tab-pane label="待确认" name="unknown" />
          <el-tab-pane label="凭证失效" name="invalid" />
        </el-tabs>
        <el-input
          v-model="searchQuery"
          :prefix-icon="Search"
          placeholder="搜索昵称或抖音号..."
          clearable
          style="width: 260px"
        />
      </div>

      <div class="account-grid" v-loading="loading">
        <article v-for="account in filteredAccounts" :key="account.id" class="account-card">
          <div class="account-head">
            <el-avatar
              :size="52"
              :src="account.avatar_url"
              class="account-avatar"
            >
              <span>{{ account.nickname.charAt(0) }}</span>
            </el-avatar>
            <div style="min-width: 0; flex: 1">
              <strong class="account-name">{{ account.nickname }}</strong>
              <div class="dy-id-text mono">{{ account.dy_id || "抖音账号" }}</div>
            </div>
            <div class="status-pill" :class="account.status">
              <span>{{ statusLabel(account.status) }}</span>
            </div>
          </div>

          <div class="account-info">
            <div class="account-info-row">
              <span class="meta">续火好友：</span>
              <strong>{{ account.active_friend_count }} / {{ account.friend_count }} 人</strong>
            </div>
            <div class="account-info-row">
              <span class="meta">Cookie 状态：</span>
              <div class="cookie-status" :class="cookieStatusClass(account)">
                {{ cookieStatusLabel(account) }}
              </div>
            </div>
            <div class="account-info-row" v-if="account.proxy_url">
              <span class="meta">专属代理：</span>
              <span class="meta mono truncate" :title="account.proxy_url">{{ account.proxy_url }}</span>
            </div>
            <div class="status-reason-box" v-if="account.status_reason">
              {{ account.status_reason }}
            </div>
          </div>

          <div class="account-actions">
            <el-button type="primary" plain size="small" @click="openFriendDialog(account)">管理好友</el-button>
            <el-button plain size="small" :loading="refreshingAccount[account.id]" @click="handleRefreshAccount(account)">同步资料</el-button>
            <el-button plain size="small" :icon="Key" @click="openCookieDialog(account)">更新凭证</el-button>
            <el-button plain size="small" :icon="Edit" @click="openEditDialog(account)">编辑</el-button>
            <el-button type="danger" plain size="small" :icon="Delete" @click="handleRemoveAccount(account)">删除</el-button>
          </div>
        </article>

        <el-empty v-if="filteredAccounts.length === 0" description="暂无符合条件的账号数据" style="grid-column: 1 / -1" />
      </div>
    </section>

    <!-- 导入新账号对话框 -->
    <el-dialog v-model="importDialogVisible" title="导入账号凭证 (Cookie)" width="620px">
      <div class="dialog-tips">
        💡 提示：在电脑浏览器登录网页版抖音 (douyin.com)，按 F12 复制 Cookie 字符串或 EditThisCookie 导出的 JSON，粘贴至下方即可自动嗅探账号与私信好友。
      </div>
      <el-input
        v-model="cookieText"
        type="textarea"
        :rows="8"
        placeholder="请粘贴完整 Cookie 凭证字符串或 JSON 格式..."
      />
      <template #footer>
        <el-button @click="importDialogVisible = false" :disabled="importing">取消</el-button>
        <el-button type="primary" @click="submitImport" :loading="importing">确认导入并同步</el-button>
      </template>
    </el-dialog>

    <!-- 更新 Cookie 对话框 -->
    <el-dialog v-model="cookieDialogVisible" title="更新账号 Cookie 凭证" width="620px">
      <p class="meta" style="margin-bottom: 12px">
        正在为账号 <strong>【{{ cookieUpdateAccount?.nickname }}】</strong> 更新凭证，原有好友与计划配置将无损保留。
      </p>
      <el-input
        v-model="cookieUpdateText"
        type="textarea"
        :rows="8"
        placeholder="请粘贴新的完整 Cookie 凭证..."
      />
      <template #footer>
        <el-button @click="cookieDialogVisible = false" :disabled="updatingCookie">取消</el-button>
        <el-button type="primary" @click="submitCookieUpdate" :loading="updatingCookie">确认更新并验证</el-button>
      </template>
    </el-dialog>

    <!-- 编辑账号信息对话框 -->
    <el-dialog v-model="editDialogVisible" title="编辑账号设置" width="480px">
      <el-form label-position="top">
        <el-form-item label="账号备注昵称">
          <el-input v-model="editForm.nickname" placeholder="给账号起个好记的名字" />
        </el-form-item>
        <el-form-item label="头像 URL (可选)">
          <el-input v-model="editForm.avatar_url" placeholder="如需自定义头像可粘贴图片地址" />
        </el-form-item>
        <el-form-item label="独立代理 URL (可选)">
          <el-input v-model="editForm.proxy_url" placeholder="例如 http://user:pass@host:port" />
          <p class="meta" style="margin-top: 4px">留空则使用服务器直连，配置独立代理可有效降低风控风险。</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitUpdate">保存修改</el-button>
      </template>
    </el-dialog>

    <!-- 好友管理对话框 -->
    <el-dialog
      v-model="friendDialogVisible"
      :title="currentAccount ? `${currentAccount.nickname} · 续火好友管理` : '好友管理'"
      width="720px"
    >
      <div class="friend-dialog-header">
        <div class="meta">{{ activeTotalText }}</div>
        <div class="friend-dialog-actions">
          <el-button size="small" plain :loading="togglingAll" :icon="Check" @click="batchToggleFriends(true)">全部激活</el-button>
          <el-button size="small" plain :loading="togglingAll" :icon="Close" @click="batchToggleFriends(false)">全部关闭</el-button>
          <el-button size="small" type="primary" plain :loading="friendLoading" :icon="Refresh" @click="refreshFriends">重新拉取私信列表</el-button>
        </div>
      </div>

      <div style="margin-bottom: 12px">
        <el-input
          v-model="friendSearchQuery"
          :prefix-icon="Search"
          placeholder="快速搜索好友昵称或抖音号..."
          clearable
          size="small"
        />
      </div>

      <div v-loading="friendLoading" class="friend-dialog-list">
        <div v-for="friend in filteredFriends" :key="friend.id" class="friend-row">
          <el-avatar :size="42" :src="friend.friend_avatar" class="avatar">
            <span>{{ friend.friend_nickname.charAt(0) }}</span>
          </el-avatar>
          <div style="min-width: 0; flex: 1">
            <strong class="friend-name-text">{{ friend.friend_nickname }}</strong>
            <div class="meta mono" style="font-size: 12px">{{ friend.friend_dy_id }}</div>
            <div v-if="friend.is_active" class="active-plan-text">
              ⏰ 计划时段 {{ friend.schedule_window }} · 下次执行 {{ formatScheduleTime(friend.next_run_at) }}
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 12px">
            <el-switch
              :model-value="friend.is_active"
              active-text="激活"
              inactive-text="关闭"
              inline-prompt
              @update:model-value="(value: boolean) => toggleFriend(friend, value)"
            />
          </div>
        </div>
        <el-empty v-if="filteredFriends.length === 0" description="未搜索到符合条件的好友" :image-size="60" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.account-info-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-reason-box {
  background: var(--bg-surface-subtle);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dialog-tips {
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  font-size: 13px;
  color: var(--primary);
  line-height: 1.6;
  margin-bottom: 14px;
}

.friend-dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.friend-dialog-actions {
  display: flex;
  gap: 8px;
}

.friend-dialog-list {
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;
}

.friend-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  background: var(--bg-surface);
  margin-bottom: 8px;
  transition: all 0.15s ease;
}

.friend-row:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.friend-name-text {
  font-size: 14px;
  color: var(--text-main);
}

.active-plan-text {
  color: var(--primary);
  font-size: 12px;
  margin-top: 2px;
  font-weight: 500;
}
</style>
