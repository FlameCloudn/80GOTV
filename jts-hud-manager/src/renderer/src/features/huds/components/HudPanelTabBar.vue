<script setup lang="ts">
// 控制面板分页（HUD 的 panel.json 里有几块就有几页）
import type { PanelSection } from '../composables/useHudPanelView'

defineProps<{ sections: PanelSection[]; activeTab: string }>()
const emit = defineEmits<{ 'update:activeTab': [value: string] }>()
</script>

<template>
  <div class="tabs">
    <button
      v-for="section in sections"
      :key="section.name"
      type="button"
      class="tab"
      :class="{ active: activeTab === section.name }"
      @click="emit('update:activeTab', section.name)"
    >
      {{ section.label }}
    </button>
  </div>
</template>

<style scoped>
.tabs { display: flex; gap: 4px; overflow-x: auto; overflow-y: hidden; border-bottom: 1px solid var(--border); }
.tab { position: relative; height: 38px; padding: 0 14px; border: none; background: transparent; color: var(--text-3); font-size: 13px; font-weight: 600; white-space: nowrap; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--text); }
.tab.active::after { content: ''; position: absolute; left: 10px; right: 10px; bottom: 0; height: 2px; border-radius: 2px; background: var(--accent); }
</style>
