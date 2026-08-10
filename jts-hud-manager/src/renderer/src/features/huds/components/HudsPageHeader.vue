<script setup lang="ts">
import BaseButton from '@renderer/components/base/BaseButton.vue';
import { ref } from 'vue';

defineProps<{
  importing: boolean;
  importError: string | null;
}>();

const emit = defineEmits<{
  'import-file': [file: File];
  refresh: [];
}>();

const zipInput = ref<HTMLInputElement | null>(null);

const onFileChange = (e: Event) => {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  emit('import-file', file);
  if (zipInput.value) zipInput.value.value = '';
};
</script>

<template>
  <div class="flex justify-between items-center mb-6">
    <div>
      <h1 class="text-2xl font-bold text-text-main">导播 HUD</h1>
      <p class="text-zinc-400 text-sm mt-1">导入、管理并启动比赛导播画面。</p>
    </div>
    <div class="flex gap-3">
      <BaseButton @click="emit('refresh')" variant="secondary">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        刷新
      </BaseButton>

      <BaseButton
        :variant="importError ? 'danger' : 'secondary'"
        :title="importError ?? ''"
        @click="zipInput?.click()"
      >
        <svg v-if="!importing" xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        {{ importing ? '正在导入...' : importError ? '导入失败' : '导入 HUD (.zip)' }}
        <input ref="zipInput" type="file" accept=".zip" class="hidden" :disabled="importing" @change="onFileChange" />
      </BaseButton>
    </div>
  </div>
</template>
