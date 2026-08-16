<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";

import { api } from "../api/client";
import type { SystemSettingsResponse } from "../types";

const settings = ref<SystemSettingsResponse | null>(null);
const loading = ref(false);
const loadError = ref("");

async function loadSettings() {
  loading.value = true;
  try {
    settings.value = await api.getSystemSettings();
    loadError.value = "";
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : "加载系统设置失败";
    ElMessage.error(loadError.value);
  } finally {
    loading.value = false;
  }
}

onMounted(loadSettings);
</script>

<template>
  <div class="view-grid" v-loading="loading">
    <el-alert
      v-if="loadError"
      class="dashboard-alert"
      :title="loadError"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>系统设置</h2>
          <p class="section-subtitle">以下参数来自服务器环境变量，修改后需要重启服务生效。</p>
        </div>
        <el-button plain :loading="loading" @click="loadSettings">刷新</el-button>
      </div>

      <div class="settings-grid">
        <div class="settings-item">
          <span class="meta">应用名称</span>
          <strong>{{ settings?.app_name ?? "-" }}</strong>
        </div>
        <div class="settings-item">
          <span class="meta">API 前缀</span>
          <strong class="mono">{{ settings?.api_prefix ?? "-" }}</strong>
        </div>
        <div class="settings-item">
          <span class="meta">管理员令牌</span>
          <el-tag :type="settings?.admin_token_configured ? 'success' : 'warning'">
            {{ settings?.admin_token_configured ? "已配置" : "未配置" }}
          </el-tag>
          <span class="meta">令牌内容不会在页面显示</span>
        </div>
        <div class="settings-item">
          <span class="meta">调度进程</span>
          <el-tag :type="settings?.scheduler_enabled ? 'success' : 'info'">
            {{ settings?.scheduler_enabled ? "已启用" : "已关闭" }}
          </el-tag>
          <span class="meta">
            {{ settings?.scheduler_enabled ? "后台会定时扫描计划" : "不会自动扫描，需手动执行" }}
          </span>
        </div>
        <div class="settings-item">
          <span class="meta">扫描间隔</span>
          <strong>{{ settings?.scheduler_scan_interval_seconds ?? "-" }} 秒</strong>
        </div>
        <div class="settings-item">
          <span class="meta">人工复核模式</span>
          <el-tag :type="settings?.manual_review_mode ? 'warning' : 'info'">
            {{ settings?.manual_review_mode ? "开启" : "关闭" }}
          </el-tag>
          <span class="meta">开启后任务只记录日志，不会真正发送</span>
        </div>
        <div class="settings-item">
          <span class="meta">数据库路径</span>
          <strong class="mono">{{ settings?.sqlite_path ?? "-" }}</strong>
        </div>
        <div class="settings-item">
          <span class="meta">密钥文件路径</span>
          <strong class="mono">{{ settings?.secret_key_path ?? "-" }}</strong>
        </div>
        <div class="settings-item">
          <span class="meta">默认续火时段</span>
          <strong>{{ settings?.default_schedule_window ?? "-" }}</strong>
        </div>
        <div class="settings-item">
          <span class="meta">CORS 允许来源</span>
          <strong class="mono">{{ (settings?.cors_origins ?? []).join("，") || "-" }}</strong>
        </div>
      </div>
    </section>

    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>调度开关说明</h2>
          <p class="section-subtitle">两个开关职责不同，不要混淆。</p>
        </div>
      </div>
      <div class="settings-note-list">
        <div>
          <strong>TIKSPARK_SCHEDULER_ENABLED（环境变量）</strong>
          <p class="meta">决定调度进程是否启动。关闭后后台完全不会自动扫描，只能手动触发。</p>
        </div>
        <div>
          <strong>自动续火花开关（页面 / 数据库）</strong>
          <p class="meta">在"自动计划"页面控制。即使调度进程在运行，关闭后扫描到点任务也不会入队执行。</p>
        </div>
        <div>
          <strong>数据备份</strong>
          <p class="meta">数据库和密钥文件必须一起备份，否则已保存的 Cookie 无法解密。上线前确认备份策略。</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.settings-item {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-strong);
}

.settings-note-list {
  display: grid;
  gap: 14px;
}

.settings-note-list > div {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-strong);
}

.settings-note-list p {
  margin: 6px 0 0;
  line-height: 1.6;
}

@media (max-width: 900px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
