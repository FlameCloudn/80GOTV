<script setup lang="ts">
// 页面标题行：英文小标签 + 中文标题 + 一句说明；右边放按钮（actions 插槽）
defineProps<{ kicker: string; title: string; description?: string }>()
</script>

<template>
  <div class="page-head">
    <div class="page-title">
      <div class="kicker">{{ kicker }}</div>
      <h1>{{ title }}</h1>
    </div>
    <p v-if="description" class="hint page-desc">{{ description }}</p>
    <div v-if="$slots.default" class="page-actions"><slot /></div>
  </div>
</template>

<style scoped>
.page-desc { padding-left: 14px; margin-left: 2px; border-left: 1px solid var(--border-strong); line-height: 1.4; }
</style>
