<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Calendar,
  ChatLineSquare,
  DataAnalysis,
  Document,
  Key,
  Setting,
  User,
  VideoPlay,
  Lock,
  Unlock,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

import { api, clearAdminToken, getAdminToken, setAdminToken } from "./api/client";

const route = useRoute();
const router = useRouter();

const navGroups = [
  {
    label: "日常运营",
    items: [
      { label: "运行看板", path: "/dashboard", icon: DataAnalysis },
      { label: "执行与任务", path: "/run", icon: VideoPlay },
      { label: "运行日志", path: "/logs", icon: Document },
    ],
  },
  {
    label: "策略配置",
    items: [
      { label: "账号管理", path: "/accounts", icon: User },
      { label: "消息与话术", path: "/messages", icon: ChatLineSquare },
      { label: "自动计划", path: "/auto-schedule", icon: Calendar },
    ],
  },
  {
    label: "系统中心",
    items: [{ label: "系统设置", path: "/settings", icon: Setting }],
  },
];

const pageTitle = computed(() => (route.meta.title as string) ?? "TikSpark Pro");
const pageCategory = computed(() => {
  for (const group of navGroups) {
    if (group.items.some((item) => item.path === route.path)) {
      return group.label;
    }
  }
  return "TikSpark Pro";
});

const tokenDialogVisible = ref(false);
const tokenDraft = ref(getAdminToken());
const savedToken = ref(getAdminToken());
const tokenSaving = ref(false);
const hasToken = computed(() => Boolean(savedToken.value));

async function saveToken() {
  const token = tokenDraft.value.trim();
  tokenSaving.value = true;
  try {
    if (!token) {
      clearAdminToken();
      savedToken.value = "";
      tokenDialogVisible.value = false;
      ElMessage.success("已清空管理员令牌");
      router.go(0);
      return;
    }

    setAdminToken(token);
    await api.getDashboardSummary();
    savedToken.value = token;
    tokenDialogVisible.value = false;
    ElMessage.success("管理员令牌验证通过");
    router.go(0);
  } catch (error) {
    clearAdminToken();
    savedToken.value = "";
    const message = error instanceof Error ? error.message : "管理员令牌验证失败";
    ElMessage.error(message);
  } finally {
    tokenSaving.value = false;
  }
}

function logoutToken() {
  clearAdminToken();
  tokenDraft.value = "";
  savedToken.value = "";
  ElMessage.success("已退出管理员访问");
  router.go(0);
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div>
        <div class="brand-section">
          <div class="brand-logo">TS</div>
          <div class="brand-info">
            <div class="brand-title">TikSpark Pro</div>
            <div class="brand-badge">自动续火花面板</div>
          </div>
        </div>

        <nav class="nav">
          <div v-for="group in navGroups" :key="group.label">
            <div class="nav-group-label">{{ group.label }}</div>
            <div class="nav-group-items">
              <button
                v-for="item in group.items"
                :key="item.path"
                class="nav-item"
                :class="{ active: route.path === item.path }"
                @click="router.push(item.path)"
              >
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
              </button>
            </div>
          </div>
        </nav>
      </div>

      <div class="sidebar-footer">
        <div class="sidebar-tip-card">
          💡 提示：Cookie 加密存储，执行时自动模拟真人行为并自动保活。
        </div>
      </div>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div class="page-header-left">
          <span class="page-category">{{ pageCategory }}</span>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="topbar-actions">
          <el-button
            :type="hasToken ? 'success' : 'default'"
            :icon="hasToken ? Unlock : Lock"
            plain
            size="default"
            @click="tokenDialogVisible = true"
          >
            {{ hasToken ? "管理员已解锁" : "输入访问令牌" }}
          </el-button>
          <el-button v-if="hasToken" plain size="default" @click="logoutToken">退出</el-button>
        </div>
      </header>

      <router-view />
    </main>

    <el-dialog v-model="tokenDialogVisible" title="管理员安全令牌" width="440px">
      <p class="dialog-hint">
        若服务器配置了 <span class="mono">TIKSPARK_ADMIN_TOKEN</span>，请输入相同令牌解锁写操作与敏感接口。
      </p>
      <el-input
        v-model="tokenDraft"
        type="password"
        show-password
        placeholder="输入管理员访问令牌"
        @keyup.enter="saveToken"
      />
      <template #footer>
        <el-button @click="tokenDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="tokenSaving" @click="saveToken">验证并保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
