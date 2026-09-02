<script setup lang="ts">
import { computed, onMounted, ref, reactive } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus, Refresh, Key, Edit, Delete, Search, Check, Close, Aim, Document, Upload } from "@element-plus/icons-vue";

import { api } from "../api/client";
import type { Account, AccountCheckResult, Friend, FriendBatchImportRequest, FriendCreateRequest, FriendUpdateRequest } from "../types";

const accounts = ref<Account[]>([]);
const loading = ref(false);
const checkingAll = ref(false);
const checkingAccount = reactive<Record<number, boolean>>({});
const refreshingAccount = reactive<Record<number, boolean>>({});
const importDialogVisible = ref(false);
const importing = ref(false);
const cookieText = ref("");
const cookieDialogVisible = ref(false);
const updatingCookie = ref(false);
const cookieUpdateText = ref("");
const cookieUpdateAccount = ref<Account | null>(null);

const batchImportDialogVisible = ref(false);
const batchImporting = ref(false);
const batchImportText = ref("");
const batchImportForm = reactive({
  schedule_window: "06:00-08:00",
  is_active: true,
  message_content: "[火花]",
});

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

// 好友管理弹窗与列表状态
const friendDialogVisible = ref(false);
const currentAccount = ref<Account | null>(null);
const currentFriends = ref<Friend[]>([]);
const friendLoading = ref(false);
const togglingAll = ref(false);
const selectedFriendIds = ref<number[]>([]);
const batchDeleting = ref(false);

// 手动添加好友弹窗
const addFriendDialogVisible = ref(false);
const addingFriend = ref(false);
const addFriendForm = reactive<FriendCreateRequest>({
  friend_nickname: "",
  friend_dy_id: "",
  friend_avatar: "",
  is_active: true,
  schedule_window: "06:00-08:00",
  frequency_days: 1,
  cooldown_minutes: 0,
  retry_limit: 2,
  retry_cooldown_minutes: 30,
  message_type: "fixed",
  message_content: "[火花]",
});

// 编辑好友弹窗
const editFriendDialogVisible = ref(false);
const editingFriend = ref(false);
const editingFriendId = ref<number>(0);
const editFriendForm = reactive<FriendUpdateRequest>({
  friend_nickname: "",
  friend_dy_id: "",
  friend_avatar: "",
  is_active: true,
  schedule_window: "06:00-08:00",
  frequency_days: 1,
  cooldown_minutes: 0,
  retry_limit: 2,
  retry_cooldown_minutes: 30,
  message_type: "fixed",
  message_content: "[火花]",
});

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

async function handleCheckSingleAccount(account: Account) {
  checkingAccount[account.id] = true;
  try {
    const res = await api.checkAccount(account.id);
    await loadAccounts();
    if (res.status === "healthy") {
      ElMessage.success(`账号【${res.nickname}】Cookie 本地结构检查完成，未从服务器登录抖音。`);
    } else {
      ElMessage.info(`账号【${res.nickname}】：${res.status_reason}`);
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "检测账号失败");
  } finally {
    checkingAccount[account.id] = false;
  }
}

async function handleCheckAllAccounts() {
  checkingAll.value = true;
  try {
    const results = await api.checkAllAccounts();
    await loadAccounts();
    const healthyCount = results.filter((r) => r.status === "healthy").length;
    ElMessage.success(`本地检查完成：共检查 ${results.length} 个账号；未从服务器登录抖音。`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "批量检测失败");
  } finally {
    checkingAll.value = false;
  }
}

async function handleRefreshAccount(account: Account) {
  try {
    await ElMessageBox.confirm(
      "同步资料会让阿里云服务器访问抖音，可能触发异地登录风控并影响电脑端会话。确定继续吗？",
      "异地登录风险提示",
      { confirmButtonText: "仍要同步", cancelButtonText: "取消", type: "warning" }
    );
  } catch {
    return;
  }
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
    ElMessage.success("Cookie 已保存；未从服务器登录抖音，也未自动同步好友");
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
    ElMessage.success("Cookie 已原样更新并保留好友配置；未进行联网保活");
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
  selectedFriendIds.value = [];
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
  try {
    await ElMessageBox.confirm(
      "同步好友会让阿里云服务器访问抖音，可能触发异地登录风控并影响电脑端会话。确定继续吗？",
      "异地登录风险提示",
      { confirmButtonText: "仍要同步", cancelButtonText: "取消", type: "warning" }
    );
  } catch {
    return;
  }
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

function openAddFriendDialog() {
  addFriendForm.friend_nickname = "";
  addFriendForm.friend_dy_id = "";
  addFriendForm.friend_avatar = "";
  addFriendForm.is_active = true;
  addFriendForm.schedule_window = "06:00-08:00";
  addFriendForm.frequency_days = 1;
  addFriendForm.cooldown_minutes = 0;
  addFriendForm.message_type = "fixed";
  addFriendForm.message_content = "[火花]";
  addFriendDialogVisible.value = true;
}

async function submitAddFriend() {
  if (!currentAccount.value) return;
  if (!addFriendForm.friend_nickname.trim() || !addFriendForm.friend_dy_id.trim()) {
    ElMessage.warning("请填写好友昵称与抖音号/sec_uid");
    return;
  }
  addingFriend.value = true;
  try {
    await api.createFriend(currentAccount.value.id, addFriendForm);
    ElMessage.success("成功添加好友！");
    addFriendDialogVisible.value = false;
    await loadFriends(currentAccount.value.id);
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "添加好友失败");
  } finally {
    addingFriend.value = false;
  }
}

function openBatchImportDialog() {
  batchImportText.value = "";
  batchImportForm.schedule_window = "06:00-08:00";
  batchImportForm.is_active = true;
  batchImportForm.message_content = "[火花]";
  batchImportDialogVisible.value = true;
}

async function submitBatchImport() {
  if (!currentAccount.value) return;
  if (!batchImportText.value.trim()) {
    ElMessage.warning("请粘贴至少一行好友信息（昵称/抖音号/sec_uid）");
    return;
  }
  batchImporting.value = true;
  try {
    const res = await api.batchImportFriends(currentAccount.value.id, {
      raw_text: batchImportText.value,
      schedule_window: batchImportForm.schedule_window,
      is_active: batchImportForm.is_active,
      message_content: batchImportForm.message_content,
    });
    ElMessage.success(res.message);
    batchImportDialogVisible.value = false;
    await loadFriends(currentAccount.value.id);
    await loadAccounts();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "批量导入失败");
  } finally {
    batchImporting.value = false;
  }
}

function openEditFriendDialog(friend: Friend) {
  editingFriendId.value = friend.id;
  editFriendForm.friend_nickname = friend.friend_nickname;
  editFriendForm.friend_dy_id = friend.friend_dy_id;
  editFriendForm.friend_avatar = friend.friend_avatar || "";
  editFriendForm.is_active = friend.is_active;
  editFriendForm.schedule_window = friend.schedule_window;
  editFriendForm.frequency_days = friend.frequency_days;
  editFriendForm.cooldown_minutes = friend.cooldown_minutes;
  editFriendForm.retry_limit = friend.retry_limit;
  editFriendForm.retry_cooldown_minutes = friend.retry_cooldown_minutes;
  editFriendForm.message_type = friend.message_type || "fixed";
  editFriendForm.message_content = friend.message_content || "[火花]";
  editFriendDialogVisible.value = true;
}

async function submitEditFriend() {
  if (!editingFriendId.value) return;
  editingFriend.value = true;
  try {
    await api.updateFriend(editingFriendId.value, editFriendForm);
    ElMessage.success("好友配置已更新！");
    editFriendDialogVisible.value = false;
    if (currentAccount.value) {
      await loadFriends(currentAccount.value.id);
      await loadAccounts();
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新好友失败");
  } finally {
    editingFriend.value = false;
  }
}

async function handleDeleteFriend(friend: Friend) {
  try {
    await ElMessageBox.confirm(
      `确定要删除好友【${friend.friend_nickname}】吗？删除后将不再向其发送续火消息。`,
      "确认删除好友",
      { confirmButtonText: "确认删除", cancelButtonText: "取消", type: "warning" }
    );
  } catch {
    return;
  }

  try {
    await api.deleteFriend(friend.id);
    ElMessage.success("好友已删除");
    if (currentAccount.value) {
      await loadFriends(currentAccount.value.id);
      await loadAccounts();
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除好友失败");
  }
}

async function handleBatchDeleteFriends() {
  if (!selectedFriendIds.value.length) {
    ElMessage.warning("请先勾选需要批量删除的好友");
    return;
  }
  try {
    await ElMessageBox.confirm(
      `确定要批量删除选中的 ${selectedFriendIds.value.length} 位好友吗？`,
      "批量删除确认",
      { confirmButtonText: "确定删除", cancelButtonText: "取消", type: "danger" }
    );
  } catch {
    return;
  }

  batchDeleting.value = true;
  try {
    const res = await api.batchDeleteFriends(selectedFriendIds.value);
    ElMessage.success(res.message);
    selectedFriendIds.value = [];
    if (currentAccount.value) {
      await loadFriends(currentAccount.value.id);
      await loadAccounts();
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "批量删除失败");
  } finally {
    batchDeleting.value = false;
  }
}

function toggleSelectAll(checked: boolean) {
  if (checked) {
    selectedFriendIds.value = filteredFriends.value.map((f) => f.id);
  } else {
    selectedFriendIds.value = [];
  }
}

function toggleSelectFriend(id: number, checked: boolean) {
  if (checked) {
    if (!selectedFriendIds.value.includes(id)) selectedFriendIds.value.push(id);
  } else {
    selectedFriendIds.value = selectedFriendIds.value.filter((i) => i !== id);
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
          <p class="section-subtitle">Cookie 凭证本地加密保存；仅在实际执行任务时使用，不进行云端联网保活。</p>
        </div>
        <div style="display: flex; gap: 10px; flex-wrap: wrap">
          <el-button type="primary" :icon="Plus" @click="importDialogVisible = true">导入新账号</el-button>
          <el-button type="warning" plain :icon="Aim" :loading="checkingAll" @click="handleCheckAllAccounts">本地检查全部 Cookie</el-button>
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
            <el-button type="success" plain size="small" :icon="Aim" :loading="checkingAccount[account.id]" @click="handleCheckSingleAccount(account)">本地检查</el-button>
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
      width="820px"
    >
      <div class="friend-dialog-header">
        <div class="meta">{{ activeTotalText }}</div>
        <div class="friend-dialog-actions">
          <el-button size="small" type="primary" :icon="Plus" @click="openAddFriendDialog">添加好友</el-button>
          <el-button size="small" type="success" plain :icon="Upload" @click="openBatchImportDialog">批量导入好友</el-button>
          <el-button size="small" plain :loading="togglingAll" :icon="Check" @click="batchToggleFriends(true)">全部激活</el-button>
          <el-button size="small" plain :loading="togglingAll" :icon="Close" @click="batchToggleFriends(false)">全部关闭</el-button>
          <el-button
            v-if="selectedFriendIds.length > 0"
            size="small"
            type="danger"
            plain
            :icon="Delete"
            :loading="batchDeleting"
            @click="handleBatchDeleteFriends"
          >
            批量删除 ({{ selectedFriendIds.length }})
          </el-button>
          <el-button size="small" type="primary" plain :loading="friendLoading" :icon="Refresh" @click="refreshFriends">同步好友（有异地风险）</el-button>
        </div>
      </div>

      <div class="friend-search-bar">
        <el-input
          v-model="friendSearchQuery"
          :prefix-icon="Search"
          placeholder="快速搜索好友昵称或抖音号..."
          clearable
          size="small"
          style="flex: 1"
        />
        <el-checkbox
          :model-value="selectedFriendIds.length === filteredFriends.length && filteredFriends.length > 0"
          :indeterminate="selectedFriendIds.length > 0 && selectedFriendIds.length < filteredFriends.length"
          @change="toggleSelectAll($event as boolean)"
        >
          全选当前列表
        </el-checkbox>
      </div>

      <div v-loading="friendLoading" class="friend-dialog-list">
        <div v-for="friend in filteredFriends" :key="friend.id" class="friend-row">
          <el-checkbox
            :model-value="selectedFriendIds.includes(friend.id)"
            @change="toggleSelectFriend(friend.id, $event as boolean)"
          />
          <el-avatar :size="42" :src="friend.friend_avatar" class="avatar">
            <span>{{ friend.friend_nickname.charAt(0) }}</span>
          </el-avatar>
          <div style="min-width: 0; flex: 1">
            <div style="display: flex; align-items: center; gap: 8px">
              <strong class="friend-name-text">{{ friend.friend_nickname }}</strong>
              <el-tag size="small" type="info" class="mono">{{ friend.friend_dy_id }}</el-tag>
            </div>
            <div v-if="friend.is_active" class="active-plan-text">
              ⏰ 计划时段 {{ friend.schedule_window }} · 下次执行 {{ formatScheduleTime(friend.next_run_at) }}
            </div>
            <div v-if="friend.message_content" class="friend-msg-preview">
              💬 {{ friend.message_content }}
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px">
            <el-button size="small" plain :icon="Edit" @click="openEditFriendDialog(friend)">编辑</el-button>
            <el-button size="small" type="danger" plain :icon="Delete" @click="handleDeleteFriend(friend)" />
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

    <!-- 手动添加好友弹窗 -->
    <el-dialog v-model="addFriendDialogVisible" title="手动添加好友" width="520px">
      <el-form label-position="top">
        <el-form-item label="好友昵称" required>
          <el-input v-model="addFriendForm.friend_nickname" placeholder="例如：小明" />
        </el-form-item>
        <el-form-item label="抖音号 / 唯一标识 / sec_uid" required>
          <el-input v-model="addFriendForm.friend_dy_id" placeholder="抖音号、搜索唯一标识或以 MS4w 开头的 sec_uid" />
        </el-form-item>
        <el-form-item label="头像 URL (可选)">
          <el-input v-model="addFriendForm.friend_avatar" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="续火时段 (24小时制)">
          <el-input v-model="addFriendForm.schedule_window" placeholder="06:00-08:00" />
        </el-form-item>
        <el-form-item label="专属续火话术">
          <el-input v-model="addFriendForm.message_content" placeholder="[火花]" />
        </el-form-item>
        <el-form-item label="立即激活续火">
          <el-switch v-model="addFriendForm.is_active" active-text="开启" inactive-text="关闭" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addFriendDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="addingFriend" @click="submitAddFriend">添加并保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑好友配置弹窗 -->
    <el-dialog v-model="editFriendDialogVisible" title="编辑好友续火配置" width="520px">
      <el-form label-position="top">
        <el-form-item label="好友昵称">
          <el-input v-model="editFriendForm.friend_nickname" />
        </el-form-item>
        <el-form-item label="抖音号 / sec_uid">
          <el-input v-model="editFriendForm.friend_dy_id" />
        </el-form-item>
        <el-form-item label="头像 URL">
          <el-input v-model="editFriendForm.friend_avatar" />
        </el-form-item>
        <el-form-item label="续火时段 (24小时制)">
          <el-input v-model="editFriendForm.schedule_window" placeholder="06:00-08:00" />
        </el-form-item>
        <el-form-item label="续火频率 (天数)">
          <el-input-number v-model="editFriendForm.frequency_days" :min="1" :max="30" />
        </el-form-item>
        <el-form-item label="发送内容 (支持 [火花] 表情标签)">
          <el-input v-model="editFriendForm.message_content" placeholder="[火花]" />
        </el-form-item>
        <el-form-item label="激活状态">
          <el-switch v-model="editFriendForm.is_active" active-text="激活" inactive-text="关闭" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editFriendDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editingFriend" @click="submitEditFriend">保存配置</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入好友弹窗 -->
    <el-dialog v-model="batchImportDialogVisible" title="批量导入续火好友" width="620px">
      <div class="dialog-tips">
        💡 提示：支持一行一个好友。格式支持 <strong>【好友昵称 抖音号】</strong> 或直接粘贴 <strong>【抖音号 / sec_uid】</strong>，多列之间支持空格、逗号或制表符分隔。
      </div>
      <el-form label-position="top">
        <el-form-item label="好友列表（每行一个）" required>
          <el-input
            v-model="batchImportText"
            type="textarea"
            :rows="8"
            placeholder="示例：&#10;小明 12345678&#10;小红 MS4wLjABAAAA_xyz...&#10;张三"
          />
        </el-form-item>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
          <el-form-item label="统一续火时段">
            <el-input v-model="batchImportForm.schedule_window" placeholder="06:00-08:00" />
          </el-form-item>
          <el-form-item label="专属续火话术">
            <el-input v-model="batchImportForm.message_content" placeholder="[火花]" />
          </el-form-item>
        </div>
        <el-form-item label="导入后立即激活续火">
          <el-switch v-model="batchImportForm.is_active" active-text="开启" inactive-text="关闭" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchImportDialogVisible = false" :disabled="batchImporting">取消</el-button>
        <el-button type="primary" :loading="batchImporting" @click="submitBatchImport">确认批量导入</el-button>
      </template>
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
  flex-wrap: wrap;
  gap: 8px;
}

.friend-dialog-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.friend-search-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
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

.friend-msg-preview {
  color: var(--text-muted);
  font-size: 12px;
  margin-top: 2px;
}
</style>
