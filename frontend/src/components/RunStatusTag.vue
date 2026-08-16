<script setup lang="ts">
import { computed } from "vue";

import type { RunStatus } from "../types";

const props = defineProps<{ status: RunStatus }>();

const labelMap: Record<string, string> = {
  pending: "等待执行",
  running: "执行中",
  success: "执行成功",
  failed: "执行失败",
  manual_review: "人工复核",
  skipped: "已跳过",
};

const typeMap: Record<string, string> = {
  success: "success",
  failed: "danger",
  manual_review: "warning",
  running: "primary",
  skipped: "info",
};

const label = computed(() => labelMap[props.status] ?? props.status);
const tagType = computed(() => typeMap[props.status] ?? "");
</script>

<template>
  <el-tag :type="tagType">{{ label }}</el-tag>
</template>
