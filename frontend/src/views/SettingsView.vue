<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { api, getAdminToken, setAdminToken } from "../api/client";
import type { AccountCheckResult, SystemSettingsResponse, SystemSettingsUpdateRequest } from "../types";

const settings = ref<SystemSettingsResponse | null>(null);
const loading = ref(false);
const saving = ref(false);
const checkingAccounts = ref(false);
const checkResults = ref<AccountCheckResult[]>([]);
const checkResultsVisible = ref(false);
const loadError = ref("");

const form = reactive<SystemSettingsUpdateRequest>({
  default_schedule_window: "06:00-08:00",
  scheduler_scan_interval_seconds: 60,
  dispatch_jitter_min_seconds: 15,
  dispatch_jitter_max_seconds: 45,
  manual_review_mode: false,
  webhook_url: "",
  admin_token: "",
});

const localToken = ref(getAdminToken());

async function loadSettings() {
  loading.value = true;
  try {
    const res = await api.getSystemSettings();
    settings.value = res;
    form.default_schedule_window = res.default_schedule_window;
    form.scheduler_scan_interval_seconds = res.scheduler_scan_interval_seconds;
    form.dispatch_jitter_min_seconds = res.dispatch_jitter_min_seconds;
    form.dispatch_jitter_max_seconds = res.dispatch_jitter_max_seconds;
    form.manual_review_mode = res.manual_review_mode;
    form.webhook_url = res.webhook_url || "";
    form.admin_token = "";
    loadError.value = "";
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : "加载系统设置失败";
    ElMessage.error(loadError.value);
  } finally {
    loading.value = false;
  }
}

async function handleSaveSettings() {
  if (form.dispatch_jitter_min_seconds! < 0 || form.dispatch_jitter_max_seconds! < form.dispatch_jitter_min_seconds!) {
    ElMessage.error("错峰等待时间配置有误：最大等待时间不能小于最小等待时间。");
    return;
  }

  saving.value = true;
  try {
    const updatePayload: SystemSettingsUpdateRequest = {
      default_schedule_window: form.default_schedule_window,
      scheduler_scan_interval_seconds: Number(form.scheduler_scan_interval_seconds),
      dispatch_jitter_min_seconds: Number(form.dispatch_jitter_min_seconds),
      dispatch_jitter_max_seconds: Number(form.dispatch_jitter_max_seconds),
      manual_review_mode: form.manual_review_mode,
      webhook_url: form.webhook_url,
    };
    if (form.admin_token && form.admin_token.trim()) {
      updatePayload.admin_token = form.admin_token.trim();
      setAdminToken(form.admin_token.trim());
      localToken.value = form.admin_token.trim();
    }

    const res = await api.updateSystemSettings(updatePayload);
    settings.value = res;
    form.admin_token = "";
    ElMessage.success("系统参数已成功保存并立即生效！");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存设置失败");
  } finally {
    saving.value = false;
  }
}

function handleSaveLocalToken() {
  setAdminToken(localToken.value);
  ElMessage.success("本地管理员令牌已同步更新！");
}

async function handleCheckAllAccounts() {
  try {
    await ElMessageBox.confirm(
      "该操作将使用无头浏览器静默访问抖音消息页与个人主页，主动校验所有账号的 Cookie 有效性，并抓取刷新最新会话凭证。是否继续？",
      "全量凭证检测与保活",
      { confirmButtonText: "立即开始", cancelButtonText: "取消", type: "info" }
    );
  } catch {
    return;
  }

  checkingAccounts.value = true;
  try {
    const results = await api.checkAllAccounts();
    checkResults.value = results;
    checkResultsVisible.value = true;
    const healthyCount = results.filter((r) => r.status === "healthy").length;
    ElMessage.success(`检测完成：共检测 ${results.length} 个账号，${healthyCount} 个状态正常。`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "检测账号失败");
  } finally {
    checkingAccounts.value = false;
  }
}

function setWindowPreset(preset: string) {
  form.default_schedule_window = preset;
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

    <!-- 可交互的系统运行参数配置 -->
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>核心运行策略与调度参数</h2>
          <p class="section-subtitle">参数修改后将持久化保存在数据库中，无需重启服务即可即时生效。</p>
        </div>
        <div class="header-actions">
          <el-button
            type="primary"
            :loading="saving"
            @click="handleSaveSettings"
          >
            保存配置
          </el-button>
          <el-button plain :loading="loading" @click="loadSettings">刷新</el-button>
        </div>
      </div>

      <el-form label-position="top" class="settings-form">
        <div class="form-row-2">
          <el-form-item label="全局默认续火时段 (24小时制)">
            <el-input
              v-model="form.default_schedule_window"
              placeholder="例如 06:00-08:00"
            />
            <div class="preset-tags">
              <span class="meta">快捷预设：</span>
              <el-tag
                size="small"
                class="tag-clickable"
                @click="setWindowPreset('06:00-08:00')"
              >
                06:00-08:00 (清晨)
              </el-tag>
              <el-tag
                size="small"
                class="tag-clickable"
                @click="setWindowPreset('07:00-09:00')"
              >
                07:00-09:00 (早间)
              </el-tag>
              <el-tag
                size="small"
                class="tag-clickable"
                @click="setWindowPreset('12:00-14:00')"
              >
                12:00-14:00 (午间)
              </el-tag>
              <el-tag
                size="small"
                class="tag-clickable"
                @click="setWindowPreset('20:00-22:00')"
              >
                20:00-22:00 (晚间)
              </el-tag>
            </div>
          </el-form-item>

          <el-form-item label="调度器后台扫描间隔 (秒)">
            <el-input-number
              v-model="form.scheduler_scan_interval_seconds"
              :min="10"
              :max="600"
              :step="10"
              style="width: 100%"
            />
            <div class="field-hint">建议 30~60 秒，控制后台检查到点任务的灵敏度。</div>
          </el-form-item>
        </div>

        <div class="form-row-2">
          <el-form-item label="任务错峰抖动等待时间范围 (秒)">
            <div class="range-inputs">
              <el-input-number
                v-model="form.dispatch_jitter_min_seconds"
                :min="0"
                :max="300"
                :step="5"
                placeholder="最小等待"
              />
              <span class="range-sep">至</span>
              <el-input-number
                v-model="form.dispatch_jitter_max_seconds"
                :min="1"
                :max="600"
                :step="5"
                placeholder="最大等待"
              />
            </div>
            <div class="field-hint">
              每次执行任务前随机等待指定秒数，模拟真人作息，大幅降低抖音风控触发几率。
            </div>
          </el-form-item>

          <el-form-item label="人工复核安全模式 (Dry-run)">
            <div class="switch-row">
              <el-switch
                v-model="form.manual_review_mode"
                active-text="开启"
                inactive-text="关闭"
              />
            </div>
            <div class="field-hint">
              开启后系统仅生成并排队任务，不会调用浏览器向好友真实发送消息，适合联调演练。
            </div>
          </el-form-item>
        </div>

        <div class="form-row-2">
          <el-form-item label="Webhook 告警机器人通知地址 (钉钉 / 飞书 / 企微)">
            <el-input
              v-model="form.webhook_url"
              placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
              clearable
            />
            <div class="field-hint">
              当账号 Cookie 失效或续火任务连续失败时，系统将主动向该 Webhook 推送告警。
            </div>
          </el-form-item>

          <el-form-item label="重置 / 更新系统管理令牌 (Admin Token)">
            <el-input
              v-model="form.admin_token"
              type="password"
              show-password
              placeholder="留空表示不修改当前令牌"
            />
            <div class="field-hint">
              设置后将更新服务器令牌并在本地浏览器自动保存。
            </div>
          </el-form-item>
        </div>

        <div class="action-footer">
          <el-button type="primary" size="large" :loading="saving" @click="handleSaveSettings">
            💾 保存配置变更
          </el-button>
          <el-button
            type="warning"
            plain
            size="large"
            :loading="checkingAccounts"
            @click="handleCheckAllAccounts"
          >
            ⚡ 一键全量检测所有账号凭证并保活
          </el-button>
        </div>
      </el-form>
    </section>

    <!-- 本地浏览器令牌管理 -->
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>本地客户端令牌 (Browser Local Storage)</h2>
          <p class="section-subtitle">控制当前浏览器向后端 API 发起请求时携带的身份验证凭据。</p>
        </div>
      </div>
      <div class="token-sync-box">
        <el-input
          v-model="localToken"
          type="password"
          show-password
          placeholder="请输入管理员令牌"
          style="max-width: 420px"
        />
        <el-button type="primary" plain @click="handleSaveLocalToken">保存至当前浏览器</el-button>
      </div>
    </section>

    <!-- 环境与只读信息 -->
    <section class="panel-card">
      <div class="section-head">
        <div>
          <h2>服务器只读环境信息</h2>
          <p class="section-subtitle">服务部署底座的基础路径与状态信息。</p>
        </div>
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
          <span class="meta">调度守护进程状态</span>
          <el-tag :type="settings?.scheduler_enabled ? 'success' : 'info'">
            {{ settings?.scheduler_enabled ? "已启用运行中" : "未启用" }}
          </el-tag>
        </div>
        <div class="settings-item">
          <span class="meta">CORS 允许来源</span>
          <strong class="mono">{{ (settings?.cors_origins ?? []).join("，") || "-" }}</strong>
        </div>
        <div class="settings-item">
          <span class="meta">SQLite 数据库路径</span>
          <strong class="mono">{{ settings?.sqlite_path ?? "-" }}</strong>
        </div>
        <div class="settings-item">
          <span class="meta">凭证加密密钥路径</span>
          <strong class="mono">{{ settings?.secret_key_path ?? "-" }}</strong>
        </div>
      </div>
    </section>

    <!-- 全量检测保活结果弹窗 -->
    <el-dialog
      v-model="checkResultsVisible"
      title="全量账号 Cookie 凭证检测与保活结果"
      width="720px"
    >
      <el-table :data="checkResults" style="width: 100%" stripe>
        <el-table-column prop="nickname" label="账号昵称" min-width="140" />
        <el-table-column prop="dy_id" label="抖音号/ID" min-width="120" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'healthy' ? 'success' : 'danger'">
              {{ row.status === 'healthy' ? '正常' : '异常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="friends_count" label="联系人数" width="90" align="center" />
        <el-table-column prop="status_reason" label="检测详情" min-width="200" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button type="primary" @click="checkResultsVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.settings-form {
  display: grid;
  gap: 16px;
  margin-top: 12px;
}

.form-row-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

@media (max-width: 768px) {
  .form-row-2 {
    grid-template-columns: 1fr;
  }
}

.range-inputs {
  display: flex;
  align-items: center;
  gap: 12px;
}

.range-sep {
  color: var(--muted);
  font-weight: 500;
}

.preset-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
}

.tag-clickable {
  cursor: pointer;
  transition: opacity 0.2s;
}

.tag-clickable:hover {
  opacity: 0.8;
}

.field-hint {
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
  line-height: 1.4;
}

.switch-row {
  display: flex;
  align-items: center;
  height: 32px;
}

.action-footer {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.token-sync-box {
  display: flex;
  align-items: center;
  gap: 12px;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}

.settings-item {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-strong);
}

.header-actions {
  display: flex;
  gap: 10px;
}
</style>
