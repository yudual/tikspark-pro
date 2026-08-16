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
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

import { api, clearAdminToken, getAdminToken, setAdminToken } from "./api/client";

const route = useRoute();
const router = useRouter();

const navGroups = [
  {
    label: "工作台",
    items: [
      { label: "运行看板", path: "/dashboard", icon: DataAnalysis },
      { label: "执行与任务", path: "/run", icon: VideoPlay },
      { label: "运行日志", path: "/logs", icon: Document },
    ],
  },
  {
    label: "配置",
    items: [
      { label: "账号管理", path: "/accounts", icon: User },
      { label: "消息配置", path: "/messages", icon: ChatLineSquare },
      { label: "自动计划", path: "/auto-schedule", icon: Calendar },
    ],
  },
  {
    label: "系统",
    items: [{ label: "系统设置", path: "/settings", icon: Setting }],
  },
];

const pageTitle = computed(() => (route.meta.title as string) ?? "TikSpark Pro");

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
      <div class="sidebar-main">
        <div>
          <div class="brand-mark">TS</div>
          <div class="brand-title">TikSpark Pro</div>
          <div class="brand-subtitle">凭证托管与关系维护面板</div>
        </div>

        <nav class="nav">
          <template v-for="group in navGroups" :key="group.label">
            <div class="nav-group-label">{{ group.label }}</div>
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
          </template>
        </nav>
      </div>

      <div class="sidebar-note">
        请仅用于个人账号的少量关系维护。上云部署时建议配置管理员令牌，并先关闭自动调度完成检查。
      </div>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div>
          <p class="eyebrow">Workspace</p>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="topbar-actions">
          <el-button :icon="Key" plain @click="tokenDialogVisible = true">
            {{ hasToken ? "管理员已解锁" : "管理员令牌" }}
          </el-button>
          <el-button v-if="hasToken" plain @click="logoutToken">退出</el-button>
        </div>
      </header>
      <router-view />
    </main>

    <el-dialog v-model="tokenDialogVisible" title="管理员访问令牌" width="420px">
      <p class="dialog-hint">
        如果云服务器配置了 <span class="mono">TIKSPARK_ADMIN_TOKEN</span>，这里需要填写同一个令牌。
        本地未配置令牌时可以留空。
      </p>
      <el-input
        v-model="tokenDraft"
        type="password"
        show-password
        placeholder="输入管理员令牌"
        @keyup.enter="saveToken"
      />
      <template #footer>
        <el-button @click="tokenDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="tokenSaving" @click="saveToken">验证并保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
