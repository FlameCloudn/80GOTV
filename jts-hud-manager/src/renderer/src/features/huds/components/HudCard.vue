<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import type { HudData } from '../composables/useHuds';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import BaseBadge from '@renderer/components/base/BaseBadge.vue';

const props = defineProps<{
  hud: HudData;
}>();

const emit = defineEmits<{
  delete: [id: string];
}>();

const router = useRouter();

const isVariantsExpanded = ref(false);
const copiedUrl = ref<string | null>(null);
const isConfirmDelete = ref(false);
const isDeleting = ref(false);

const buildUrl = (url: string, variant?: string): string => {
  if (!variant) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}variant=${encodeURIComponent(variant)}`;
};

const launchHud = (url: string, variant?: string) => {
  const finalUrl = buildUrl(url, variant);
  if (window.electron?.ipcRenderer) {
    window.electron.ipcRenderer.send('open-hud', finalUrl);
  } else {
    window.open(finalUrl, '_blank');
  }
};

const copyUrl = (url: string) => {
  navigator.clipboard.writeText(url);
  copiedUrl.value = url;
  setTimeout(() => { copiedUrl.value = null; }, 1500);
};

const handleDelete = async () => {
  if (!isConfirmDelete.value) {
    isConfirmDelete.value = true;
    setTimeout(() => { isConfirmDelete.value = false; }, 3000);
    return;
  }
  isDeleting.value = true;
  isConfirmDelete.value = false;
  emit('delete', props.hud.id);
};

const nonMainVariants = props.hud.config.variants?.filter(v => v.toLowerCase() !== 'main') ?? [];
</script>

<template>
  <div class="bg-surface border border-zinc-700 rounded-lg p-5 flex flex-col group transition-all hover:border-primary/50 hover:shadow hover:shadow-primary/20"> 

    <!-- Top row: info + action buttons -->
    <div class="flex justify-between items-center gap-4">
      <div class="flex items-center gap-3 flex-1 min-w-0">
        <!-- Thumbnail -->
        <img
          v-if="hud.thumb"
          :src="hud.thumb"
          :alt="hud.config.name"
          class="w-16 h-16 rounded-lg object-cover shrink-0 border border-zinc-700"
        />
        <div v-else class="w-16 h-16 rounded-lg shrink-0 border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-600">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.75 3H5.25A2.25 2.25 0 003 5.25v13.5A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V9.75m-11.25 0V3m0 6.75h6M9.75 3l6 6.75" />
          </svg>
        </div>
        <div class="min-w-0">
          <div class="flex items-center gap-3 mb-1">
            <h3 class="font-bold text-lg text-text-main">{{ hud.config.name }}</h3>
            <BaseBadge variant="blue">
              v{{ hud.config.version }}
            </BaseBadge>
            <BaseBadge v-if="hud.isSigned && hud.signatureVerified" variant="emerald" class="flex items-center gap-1">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
              </svg>
              已验证
            </BaseBadge>
            <BaseBadge v-else-if="hud.isSigned" variant="amber" class="flex items-center gap-1" title="这个 HUD 带有签名，但无法验证，文件可能被修改过。">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
              </svg>
              未验证
            </BaseBadge>
          </div>
          <div class="text-sm text-zinc-400">作者：{{ hud.config.author || '未知' }}</div>
        </div>
      </div>

      <div class="flex flex-col items-end gap-1 shrink-0">
        <div class="flex items-start gap-2">
          <BaseButton
            variant="secondary"
            v-if="nonMainVariants.length > 0"
            @click="isVariantsExpanded = !isVariantsExpanded"          >
            <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5 transition-transform" :class="{ 'rotate-180': isVariantsExpanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
            其他布局
          </BaseButton>

          <BaseButton
            variant="secondary"
            v-if="hud.hasPanel"
            @click="router.push(`/huds/${hud.id}/panel`)"
            title="打开控制面板"
          >
            控制面板
          </BaseButton>

          <BaseButton
            v-if="hud.canDelete !== false"
            @click="handleDelete"
            :disabled="isDeleting"
            :variant="isConfirmDelete ? 'danger' : 'secondary'"
            :title="isConfirmDelete ? '再次点击确认删除' : '删除 HUD'"
          >
            <svg v-if="isConfirmDelete" xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
            </svg>
            <svg v-else-if="!isDeleting" xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
            {{ isConfirmDelete ? '确认删除？' : isDeleting ? '...' : '删除' }}
          </BaseButton>

          <div class="flex flex-col items-center gap-1">
            <BaseButton @click="launchHud(hud.url)" variant="primary" size="lg">
              启动导播画面
            </BaseButton>
            <BaseButton @click="copyUrl(hud.url)" variant="ghost" size="sm">
              <svg v-if="copiedUrl !== hud.url" xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2"/>
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
              </svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" class="w-3 h-3 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
              </svg>
              {{ copiedUrl === hud.url ? '已复制！' : '复制 OBS 地址' }}
            </BaseButton>
          </div>
        </div>
      </div>
    </div>

    <!-- Collapsible variants row -->
    <div
      v-if="nonMainVariants.length > 0 && isVariantsExpanded"
      class="border-t border-zinc-700 pt-3 mt-3"
    >
      <div class="flex flex-wrap gap-2">
        <div
          v-for="variant in nonMainVariants"
          :key="variant"
          class="flex items-center rounded overflow-hidden border border-zinc-600"
        >

        <!-- TODO: Utilize BaseButton -->
          <button
            @click="launchHud(hud.url, variant)"
            class="bg-zinc-700 hover:bg-blue-600 text-zinc-200 hover:text-text-main text-xs font-medium py-1.5 px-3 transition-colors"
          >
            {{ variant }}
          </button>
          <button
            @click="copyUrl(buildUrl(hud.url, variant))"
            :title="copiedUrl === buildUrl(hud.url, variant) ? '已复制！' : '复制地址'"
            class="bg-zinc-800 hover:bg-zinc-600 text-zinc-400 hover:text-zinc-200 text-xs py-1.5 px-2 transition-colors border-l border-zinc-600 flex items-center gap-1"
          >
            <svg v-if="copiedUrl !== buildUrl(hud.url, variant)" xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2"/>
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
            </svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" class="w-3 h-3 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
            </svg>
            {{ copiedUrl === buildUrl(hud.url, variant) ? '已复制' : '复制' }}
          </button>
        </div>
      </div>
    </div>

  </div>
</template>
