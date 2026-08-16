<script setup lang="ts">
import type { Account } from "../types";

defineProps<{
  accounts: Account[];
  modelValue: number | null;
  placeholder?: string;
}>();

defineEmits<{ "update:modelValue": [value: number | null] }>();
</script>

<template>
  <el-select
    :model-value="modelValue"
    clearable
    :placeholder="placeholder ?? '全部账号'"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option label="全部账号" :value="null" />
    <el-option
      v-for="account in accounts"
      :key="account.id"
      :label="account.nickname"
      :value="account.id"
    />
  </el-select>
</template>
