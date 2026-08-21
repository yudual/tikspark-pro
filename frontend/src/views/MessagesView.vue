<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { User } from "@element-plus/icons-vue";

import { api } from "../api/client";
import type { MessageRow, MessageType } from "../types";

type MessageEditor = {
  messageType: MessageType;
  messageContent: string;
};

const rows = ref<MessageRow[]>([]);
const loading = ref(false);
const saving = reactive<Record<number, boolean>>({});
const savingAll = ref(false);
const editors = reactive<Record<number, MessageEditor>>({});

const filterAccountId = ref<number | null>(null);
const activeCollapse = ref<number[]>([]);

const batchDialogVisible = ref(false);
const batchSubmitting = ref(false);
const batchForm = reactive({
  accountId: null as number | null,
  messageType: "fixed" as MessageType,
  messageContent: "",
});

const libraryDialogVisible = ref(false);
const librarySubmitting = ref(false);
const activeLibraryRow = ref<MessageRow | null>(null);
const libraryDraft = ref("");

const uniqueAccounts = computed(() => {
  const map = new Map<number, { id: number; name: string }>();
  for (const row of rows.value) {
    if (!map.has(row.account_id)) {
      map.set(row.account_id, { id: row.account_id, name: row.account_name });
    }
  }
  return Array.from(map.values());
});

const filteredRows = computed(() => {
  if (!filterAccountId.value) return rows.value;
  return rows.value.filter((row) => row.account_id === filterAccountId.value);
});

const groupedRows = computed(() => {
  const groups = new Map<
    number,
    { accountId: number; accountName: string; accountStatus: string; rows: MessageRow[] }
  >();
  for (const row of filteredRows.value) {
    if (!groups.has(row.account_id)) {
      groups.set(row.account_id, {
        accountId: row.account_id,
        accountName: row.account_name,
        accountStatus: row.account_status,
        rows: [],
      });
    }
    groups.get(row.account_id)!.rows.push(row);
  }
  return Array.from(groups.values());
});

const defaultRandomLibrary = computed(() => {
  for (const row of rows.value) {
    const editor = editors[row.friend_id];
    const content = editor?.messageContent || row.message_content;
    const type = editor?.messageType || row.message_type;
    if (type === "random" && countRandomEntries(content) >= 2) {
      return content;
    }
  }
  return "";
});

watch(groupedRows, (groups) => {
  if (activeCollapse.value.length === 0 && groups.length > 0) {
    activeCollapse.value = groups.map((group) => group.accountId);
  }
});

function ensureEditor(row: MessageRow) {
  if (!editors[row.friend_id]) {
    editors[row.friend_id] = {
      messageType: row.message_type,
      messageContent: row.message_content,
    };
  }
  return editors[row.friend_id];
}

function countRandomEntries(content: string) {
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean).length;
}

function appendSparkToken(value: string) {
  if ((value ?? "").trimEnd().endsWith("[火花]")) {
    ElMessage.info("这条内容末尾已经有火花表情了");
    return value;
  }
  return value ? `${value} [火花]` : "[火花]";
}

function insertSparkToEditor(row: MessageRow) {
  const editor = ensureEditor(row);
  editor.messageContent = appendSparkToken(editor.messageContent);
}

function insertSparkToLibrary() {
  libraryDraft.value = appendSparkToken(libraryDraft.value);
}

function insertSparkToBatch() {
  batchForm.messageContent = appendSparkToken(batchForm.messageContent);
}

function randomPreview(content: string) {
  const entries = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (entries.length === 0) return "还没有配置话术";
  return entries
    .slice(0, 2)
    .join(" / ")
    .replace(/\[火花\]/g, "🔥");
}

function validateEditor(messageType: MessageType, messageContent: string) {
  if (messageType === "fixed" && !messageContent.trim()) {
    ElMessage.warning("固定文本不能为空");
    return false;
  }
  if (messageType === "random" && countRandomEntries(messageContent) < 2) {
    ElMessage.warning("随机话术库至少需要 2 条话术，每行一条。");
    return false;
  }
  return true;
}

function onMessageTypeChange(row: MessageRow) {
  const editor = ensureEditor(row);
  if (editor.messageType === "sticker") {
    editor.messageContent = "";
    return;
  }
  if (editor.messageType === "fixed") {
    if (defaultRandomLibrary.value && editor.messageContent === defaultRandomLibrary.value) {
      editor.messageContent = "";
    }
    return;
  }

  if (countRandomEntries(editor.messageContent) >= 2) return;

  if (defaultRandomLibrary.value) {
    editor.messageContent = defaultRandomLibrary.value;
    ElMessage.success("已自动套用默认随机话术库");
    return;
  }

  openLibraryDialog(row);
}

function openLibraryDialog(row: MessageRow) {
  const editor = ensureEditor(row);
  activeLibraryRow.value = row;
  libraryDraft.value = editor.messageContent;
  libraryDialogVisible.value = true;
}

async function submitLibraryDialog() {
  if (!activeLibraryRow.value) return;
  if (!validateEditor("random", libraryDraft.value)) return;

  const row = activeLibraryRow.value;
  const editor = ensureEditor(row);
  editor.messageType = "random";
  editor.messageContent = libraryDraft.value;

  librarySubmitting.value = true;
  try {
    await saveRow(row, { quiet: true });
    libraryDialogVisible.value = false;
    ElMessage.success("随机话术库已保存");
  } finally {
    librarySubmitting.value = false;
  }
}

function openBatchDialog() {
  batchForm.accountId = null;
  batchForm.messageType = "fixed";
  batchForm.messageContent = "";
  batchDialogVisible.value = true;
}

function onBatchMessageTypeChange() {
  if (batchForm.messageType === "sticker") {
    batchForm.messageContent = "";
    return;
  }
  if (batchForm.messageType === "random" && countRandomEntries(batchForm.messageContent) < 2) {
    batchForm.messageContent = defaultRandomLibrary.value;
  } else if (batchForm.messageType === "fixed" && batchForm.messageContent === defaultRandomLibrary.value) {
    batchForm.messageContent = "";
  }
}

async function submitBatchUpdate() {
  if (!validateEditor(batchForm.messageType, batchForm.messageContent)) return;

  const targetText = batchForm.accountId
    ? `账号 ${uniqueAccounts.value.find((account) => account.id === batchForm.accountId)?.name} 下的所有启用好友`
    : "所有账号的启用好友";

  try {
    await ElMessageBox.confirm(
      `确定要将配置一键应用到 ${targetText} 吗？这会覆盖他们原有的消息设置。`,
      "批量应用",
      { type: "warning", confirmButtonText: "确定覆盖" },
    );
  } catch {
    return;
  }

  batchSubmitting.value = true;
  try {
    const res = await api.batchUpdateMessages(
      batchForm.messageType,
      batchForm.messageContent,
      batchForm.accountId ?? undefined,
    );
    ElMessage.success(`批量配置成功，共更新 ${res.updated_count} 个好友`);
    batchDialogVisible.value = false;
    await loadRows();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "批量更新失败");
  } finally {
    batchSubmitting.value = false;
  }
}

async function loadRows() {
  loading.value = true;
  try {
    rows.value = await api.listMessages();
    for (const row of rows.value) {
      editors[row.friend_id] = {
        messageType: row.message_type,
        messageContent: row.message_content,
      };
    }
    const library = defaultRandomLibrary.value;
    if (library) {
      for (const row of rows.value) {
        const editor = editors[row.friend_id];
        if (editor.messageType === "random" && countRandomEntries(editor.messageContent) < 2) {
          editor.messageContent = library;
        }
      }
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载消息失败");
  } finally {
    loading.value = false;
  }
}

async function manualRefresh() {
  await loadRows();
  ElMessage.success("消息配置已刷新");
}

async function saveAll() {
  savingAll.value = true;
  let successCount = 0;
  try {
    for (const row of rows.value) {
      const editor = editors[row.friend_id];
      if (!editor) continue;
      if (editor.messageType === row.message_type && editor.messageContent === row.message_content) {
        continue;
      }
      if (!validateEditor(editor.messageType, editor.messageContent)) {
        continue;
      }
      await saveRow(row, { quiet: true });
      successCount++;
    }

    if (successCount > 0) {
      ElMessage.success(`一键保存成功，共更新 ${successCount} 个好友的配置`);
    } else {
      ElMessage.info("没有需要保存的修改");
    }
  } catch {
    ElMessage.error("部分配置保存失败，请检查后重试");
  } finally {
    savingAll.value = false;
  }
}

async function saveRow(row: MessageRow, options: { quiet?: boolean } = {}) {
  const editor = ensureEditor(row);
  if (!validateEditor(editor.messageType, editor.messageContent)) return;

  saving[row.friend_id] = true;
  try {
    const updated = await api.updateMessage(
      row.friend_id,
      editor.messageType,
      editor.messageContent,
    );
    const index = rows.value.findIndex((item) => item.friend_id === row.friend_id);
    if (index >= 0) rows.value[index] = updated;
    editors[row.friend_id] = {
      messageType: updated.message_type,
      messageContent: updated.message_content,
    };
    if (!options.quiet) ElMessage.success("消息已保存");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败");
    throw error;
  } finally {
    saving[row.friend_id] = false;
  }
}

onMounted(loadRows);
</script>

<template>
  <div class="view-grid">
    <section class="panel-card">
      <div class="section-head message-head">
        <div>
          <h2>消息配置</h2>
          <p class="section-subtitle">三种模式：固定文本 / 随机话术库 / 火花表情。文本中也可用 [火花] 占位符插入续火花表情。</p>
        </div>
        <div class="message-actions">
          <el-select v-model="filterAccountId" placeholder="全部账号" clearable>
            <el-option label="全部账号" :value="null" />
            <el-option
              v-for="acc in uniqueAccounts"
              :key="acc.id"
              :label="acc.name"
              :value="acc.id"
            />
          </el-select>
          <el-button type="success" :loading="savingAll" @click="saveAll">一键保存</el-button>
          <el-button type="primary" plain @click="openBatchDialog">批量应用配置</el-button>
          <el-button plain :loading="loading" @click="manualRefresh">刷新</el-button>
        </div>
      </div>

      <div v-loading="loading">
        <el-empty v-if="groupedRows.length === 0" description="暂无启用好友需要配置消息" />

        <el-collapse v-model="activeCollapse" class="custom-collapse">
          <el-collapse-item
            v-for="group in groupedRows"
            :key="group.accountId"
            :name="group.accountId"
          >
            <template #title>
              <div class="message-group-title">
                <el-icon><User /></el-icon>
                <strong>{{ group.accountName }}</strong>
                <el-tag size="small" :type="group.accountStatus === 'healthy' ? 'success' : 'warning'">
                  {{ group.accountStatus }}
                </el-tag>
                <span class="meta">共 {{ group.rows.length }} 个启用好友</span>
              </div>
            </template>

            <el-table :data="group.rows" stripe>
              <el-table-column label="续火好友" min-width="150">
                <template #default="{ row }">
                  {{ row.friend_name }}
                </template>
              </el-table-column>

              <el-table-column label="消息模式" width="170">
                <template #default="{ row }">
                  <el-select
                    v-model="ensureEditor(row).messageType"
                    @change="onMessageTypeChange(row)"
                  >
                    <el-option label="固定文本" value="fixed" />
                    <el-option label="随机话术库" value="random" />
                    <el-option label="火花表情" value="sticker" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="消息配置" min-width="280">
                <template #default="{ row }">
                  <el-input
                    v-if="ensureEditor(row).messageType === 'fixed'"
                    v-model="ensureEditor(row).messageContent"
                    placeholder="文本内容，可用 [火花] 追加一条续火花表情"
                  >
                    <template #append>
                      <el-button @click="insertSparkToEditor(row)">+ 火花</el-button>
                    </template>
                  </el-input>
                  <div v-else-if="ensureEditor(row).messageType === 'sticker'" class="sticker-hint">
                    🔥 执行时自动打开抖音表情面板，发送续火花表情包
                  </div>
                  <div v-else class="library-summary">
                    <div>
                      <strong>随机话术库</strong>
                      <span>{{ countRandomEntries(ensureEditor(row).messageContent) }} 条话术</span>
                    </div>
                    <p>{{ randomPreview(ensureEditor(row).messageContent) }}</p>
                    <el-button size="small" plain type="primary" @click="openLibraryDialog(row)">
                      编辑话术库
                    </el-button>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="操作" width="90" align="right">
                <template #default="{ row }">
                  <div class="message-row-actions">
                    <el-button
                      type="primary"
                      plain
                      size="small"
                      :loading="saving[row.friend_id]"
                      @click="saveRow(row)"
                    >
                      保存
                    </el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </div>
    </section>

    <el-dialog v-model="libraryDialogVisible" title="编辑随机话术库" width="620px">
      <div class="library-editor">
        <el-input
          v-model="libraryDraft"
          type="textarea"
          :rows="10"
          placeholder="每行一条话术，至少填写 2 条。执行时会随机选择其中一条。话术中可用 [火花] 追加一条续火花表情。"
        />
        <div class="library-toolbar">
          <el-button size="small" plain @click="insertSparkToLibrary">
            插入火花表情
          </el-button>
          <span class="meta">[火花] 发送时会自动点击抖音表情面板里的续火花表情。</span>
        </div>
        <p class="meta">当前已收录 {{ countRandomEntries(libraryDraft) }} 条话术。</p>
      </div>
      <template #footer>
        <el-button @click="libraryDialogVisible = false" :disabled="librarySubmitting">取消</el-button>
        <el-button type="primary" @click="submitLibraryDialog" :loading="librarySubmitting">
          保存话术库
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchDialogVisible" title="批量应用消息配置" width="620px">
      <el-form label-position="top">
        <el-form-item label="目标账号">
          <el-select v-model="batchForm.accountId" placeholder="默认应用于所有账号" clearable style="width: 100%">
            <el-option label="应用于所有账号的启用好友" :value="null" />
            <el-option
              v-for="acc in uniqueAccounts"
              :key="acc.id"
              :label="acc.name"
              :value="acc.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="消息模式">
          <el-radio-group v-model="batchForm.messageType" @change="onBatchMessageTypeChange">
            <el-radio value="fixed">固定文本</el-radio>
            <el-radio value="random">随机话术库</el-radio>
            <el-radio value="sticker">火花表情</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item :label="batchForm.messageType === 'random' ? '话术库内容' : batchForm.messageType === 'sticker' ? '续火花表情' : '固定消息内容'">
          <div v-if="batchForm.messageType === 'sticker'" class="library-editor">
            <div class="sticker-hint">🔥 执行时自动打开抖音表情面板，发送续火花表情包</div>
          </div>
          <div v-else class="library-editor">
            <el-input
              v-model="batchForm.messageContent"
              type="textarea"
              :rows="batchForm.messageType === 'random' ? 8 : 4"
              :placeholder="batchForm.messageType === 'random'
                ? '每行一条话术，至少填写 2 条。话术中可用 [火花] 追加一条续火花表情。'
                : '请输入要统一应用的固定消息内容，可用 [火花] 追加一条续火花表情。'"
            />
            <div class="library-toolbar">
              <el-button size="small" plain @click="insertSparkToBatch">插入火花表情</el-button>
              <span class="meta">[火花] 会先发送前面的文字，再单独发一条续火花表情。</span>
            </div>
            <p v-if="batchForm.messageType === 'random'" class="meta">
              当前已收录 {{ countRandomEntries(batchForm.messageContent) }} 条话术。
            </p>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDialogVisible = false" :disabled="batchSubmitting">取消</el-button>
        <el-button type="primary" @click="submitBatchUpdate" :loading="batchSubmitting">
          确定覆盖
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.message-head {
  align-items: flex-start;
}

.message-actions {
  display: grid;
  grid-template-columns: 190px auto auto auto;
  gap: 10px;
  align-items: center;
}

.message-group-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 16px;
}

.library-summary {
  display: grid;
  gap: 6px;
  max-width: 100%;
}

.library-summary > div {
  display: flex;
  align-items: center;
  gap: 10px;
}

.library-summary span {
  color: var(--muted);
  font-size: 13px;
}

.library-summary p {
  margin: 0;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-row-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.library-editor {
  display: grid;
  gap: 8px;
  width: 100%;
}

.library-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sticker-hint {
  color: var(--muted);
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 13px;
}

@media (max-width: 900px) {
  .message-head {
    display: grid;
  }

  .message-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 620px) {
  .message-actions {
    grid-template-columns: 1fr;
  }
}
</style>
