<script setup lang="ts">
import BaseButton from '@renderer/components/base/BaseButton.vue';
import { useRouter } from 'vue-router';

defineProps<{
  hudId: string;
}>();

const router = useRouter();
</script>

<template>
  <div class="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
    <div class="flex items-center gap-3">
      <BaseButton variant="ghost" @click="router.push('/huds')">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
        </svg>
      </BaseButton>
      <div>
        <h1 class="text-xl font-bold text-text-main">HUD 控制面板</h1>
        <p class="text-zinc-500 text-xs mt-0.5">{{ hudId }}</p>
      </div>
    </div>
  </div>
</template>
