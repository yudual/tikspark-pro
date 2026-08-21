<script setup lang="ts">
import { computed, onMounted, ref, reactive } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus, Refresh, Key, Edit, Delete, Search, UserFilled, CircleCheck } from "@element-plus/icons-vue";

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
  return `已激活 ${currentAccount.value.active_friend_count}/${currentAccount.value.friend_count} 个好友`;
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
  if (!account.cookie_expires_at) return "Cookie 状态正常";
  const diffMs = new Date(account.cookie_expires_at).getTime() - Date.now();
  if (diffMs <= 0) return "Cookie 已过期，请及时更新";
  const days = Math.floor(diffMs / 86400000);
  if (days <= 1) return "Cookie 即将到期";
  return `Cookie 约 ${days} 天后到期`;
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
    ElMessage.success(account.avatar_url ? "账号与好友资料已重新同步" : "已重新尝试嗅探账号与好友列表");
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
    ElMessage.success("账号已成功导入并同步联系人");
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
    ElMessage.success("Cookie 已更新，原有好友与配置已无损保留");
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
          <p class="section-subtitle">Cookie 加密保存在本地，执行时支持自动刷新保活与防风控错峰。</p>
        </div>
        <div style="display: flex; gap: 12px">
          <el-button type="primary" :icon="Plus" @click="importDialogVisible = true">导入新账号凭证</el-button>
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
              <div class="meta mono dy-id-text" :title="account.dy_id">{{ account.dy_id || "抖音账号" }}</div>
            </div>
          </div>

          <div class="status-pill" :class="account.status">
            <span>{{ statusLabel(account.status) }}</span>
          </div>

          <div class="account-info">
            <div class="meta">已激活 <strong>{{ account.active_friend_count }}</strong> / {{ account.friend_count }} 位好友续火</div>
            <div class="cookie-status" :class="cookieStatusClass(account)">
              {{ cookieStatusLabel(account) }}
            </div>
            <div class="meta">最近刷新：{{ formatCookieDate(account.cookie_updated_at || account.last_checked_at) }}</div>
            <div class="meta truncate" v-if="account.proxy_url" :title="account.proxy_url">
              代理: {{ account.proxy_url }}
            </div>
            <div class="meta status-reason">{{ account.status_reason }}</div>
          </div>

          <div class="account-actions">
            <el-button type="primary" plain @click="openFriendDialog(account)">管理好友</el-button>
            <el-button plain :loading="refreshingAccount[account.id]" @click="handleRefreshAccount(account)">同步资料</el-button>
            <el-button plain :icon="Key" @click="openCookieDialog(account)">更新 Cookie</el-button>
            <el-button plain :icon="Edit" @click="openEditDialog(account)">编辑</el-button>
            <el-button type="danger" plain :icon="Delete" @click="handleRemoveAccount(account)">删除</el-button>
          </div>
        </article>
      </div>
    </section>

    <!-- 导入新账号对话框 -->
    <el-dialog v-model="importDialogVisible" title="导入账号凭证 (Cookie)" width="640px">
      <div class="dialog-tips">
        💡 提示：在电脑浏览器登录网页版抖音 (douyin.com)，按 F12 打开开发者工具复制完整 Cookie 字符串或 EditThisCookie JSON 格式，粘贴在下方即可。系统将自动提取账号昵称与私信好友。
      </div>
      <el-input
        v-model="cookieText"
        type="textarea"
        :rows="8"
        placeholder="请粘贴完整 Cookie 凭证字符串或 JSON 格式"
      />
      <template #footer>
        <el-button @click="importDialogVisible = false" :disabled="importing">取消</el-button>
        <el-button type="primary" @click="submitImport" :loading="importing">确认导入并同步</el-button>
      </template>
    </el-dialog>

    <!-- 更新 Cookie 对话框 -->
    <el-dialog v-model="cookieDialogVisible" title="更新账号 Cookie 凭证" width="640px">
      <p class="meta" style="margin-top: 0">
        正在为账号 <strong>【{{ cookieUpdateAccount?.nickname }}】</strong> 更新凭证。更新后将保留原有全部好友、话术和自动计划配置。
      </p>
      <el-input
        v-model="cookieUpdateText"
        type="textarea"
        :rows="8"
        placeholder="请粘贴新的完整 Cookie 凭证"
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
          <p class="meta" style="margin-top: 4px">留空则使用本地/服务器网络直连。多账号建议配置不同代理以降低风控概率。</p>
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
      width="760px"
    >
      <div class="friend-dialog-header">
        <div class="meta">{{ activeTotalText }}</div>
        <div class="friend-dialog-actions">
          <el-button size="small" plain :loading="togglingAll" @click="batchToggleFriends(true)">全部激活</el-button>
          <el-button size="small" plain :loading="togglingAll" @click="batchToggleFriends(false)">全部关闭</el-button>
          <el-button size="small" type="primary" plain :loading="friendLoading" @click="refreshFriends">重新拉取私信列表</el-button>
        </div>
      </div>

      <div style="margin-bottom: 12px">
        <el-input
          v-model="friendSearchQuery"
          :prefix-icon="Search"
          placeholder="搜索好友昵称或抖音号..."
          clearable
          size="small"
        />
      </div>

      <div v-loading="friendLoading" class="friend-dialog-list">
        <div v-for="friend in filteredFriends" :key="friend.id" class="friend-row">
          <el-avatar :size="44" :src="friend.friend_avatar" class="avatar">
            <span>{{ friend.friend_nickname.charAt(0) }}</span>
          </el-avatar>
          <div style="min-width: 0; flex: 1">
            <strong class="friend-name-text">{{ friend.friend_nickname }}</strong>
            <div class="meta mono">{{ friend.friend_dy_id }}</div>
            <div v-if="friend.is_active" class="meta active-plan-text">
              ⏰ 时段 {{ friend.schedule_window }} · 下次 {{ formatScheduleTime(friend.next_run_at) }}
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
        <el-empty v-if="filteredFriends.length === 0" description="未搜索到符合条件的好友" />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.dialog-tips {
  background: rgba(15, 118, 110, 0.08);
  border: 1px solid rgba(15, 118, 110, 0.2);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 13px;
  color: var(--primary, #0f766e);
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
  border-radius: 10px;
  border: 1px solid var(--border, rgba(15, 23, 42, 0.08));
  background: var(--surface, #ffffff);
  margin-bottom: 8px;
  transition: all 0.2s ease;
}

.friend-row:hover {
  background: #f8fafc;
  border-color: rgba(15, 118, 110, 0.3);
}

.friend-name-text {
  font-size: 14px;
  color: var(--text, #0f172a);
}

.active-plan-text {
  color: var(--primary, #0f766e);
  font-size: 12px;
  margin-top: 2px;
}
</style>
