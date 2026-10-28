<script setup lang="ts">
// 勾选了选手后出现：显示选了几名 + 删除选中项
import AppIcon from '../../../components/ui/AppIcon.vue'

defineProps<{ selectedCount: number }>()
defineEmits<{ deleteSelected: [] }>()
</script>

<template>
  <div class="bulk-bar">
    <span>已选择 <b class="num">{{ selectedCount }}</b> 名选手</span>
    <button type="button" class="btn btn-danger btn-sm" @click="$emit('deleteSelected')"><AppIcon name="trash" />删除选中项</button>
  </div>
</template>

<style scoped>
.bulk-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 10px 8px 14px; border-radius: var(--radius-md); background: var(--accent-soft); border: 1px solid rgba(107, 159, 209, 0.35); font-size: 13px; color: var(--text-2); }
.bulk-bar b { color: var(--accent); }
</style>
