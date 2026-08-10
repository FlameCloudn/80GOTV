<script setup lang="ts">
import { useHudsView } from '../features/huds/composables/useHudsView';
import HudsPageHeader from '../features/huds/components/HudsPageHeader.vue';
import HudCard from '../features/huds/components/HudCard.vue';

const { huds, isLoading, fetchHuds, deleteHud, importing, importError, handleZipImport } = useHudsView();
</script>

<template>
  <div class="p-6 bg-surface text-zinc-200 min-h-screen">
    <HudsPageHeader
      :importing="importing"
      :import-error="importError"
      @import-file="handleZipImport"
      @refresh="fetchHuds"
    />

    <div class="bg-zinc-800 p-6 rounded-xl border border-zinc-700">
      <div v-if="isLoading" class="text-center py-12 text-zinc-400">正在扫描 HUD...</div>

      <div v-else-if="huds.length === 0" class="text-center py-12 flex flex-col items-center">
        <div class="text-zinc-400 mb-2">还没有找到可用的 HUD。</div>
        <div class="text-sm text-zinc-500">点击右上角“导入 HUD”并选择 zip 文件。</div>
      </div>

      <div v-else class="grid gap-4">
        <HudCard v-for="hud in huds" :key="hud.id" :hud="hud" @delete="deleteHud" />
      </div>
    </div>
  </div>
</template>
