<script setup lang="ts">
import type { PanelSection } from '../composables/useHudPanelView';

defineProps<{
  sections: PanelSection[];
  activeTab: string;
}>();

const emit = defineEmits<{
  'update:activeTab': [value: string];
}>();
</script>

<template>
  <div class="flex border-b border-border px-6 shrink-0 overflow-x-auto">
    <button
      v-for="section in sections"
      :key="section.name"
      @click="emit('update:activeTab', section.name)"
      :class="[
        'px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px',
        activeTab === section.name
          ? 'text-text-main border-primary'
          : 'text-zinc-400 border-transparent hover:text-zinc-200 hover:border-zinc-700'
      ]"
    >
      {{ section.label }}
    </button>
  </div>
</template>
