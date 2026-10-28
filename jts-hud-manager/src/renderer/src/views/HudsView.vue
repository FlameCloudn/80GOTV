<script setup lang="ts">
// 导播 HUD：本机可用的 HUD 列表
import AppIcon from '../components/ui/AppIcon.vue'
import HudsPageHeader from '../features/huds/components/HudsPageHeader.vue'
import HudCard from '../features/huds/components/HudCard.vue'
import { useHudsView } from '../features/huds/composables/useHudsView'

const { huds, isLoading, fetchHuds, deleteHud, importing, importError, handleZipImport } = useHudsView()
</script>

<template>
  <div class="page">
    <HudsPageHeader :importing="importing" :import-error="importError" @import-file="handleZipImport" @refresh="fetchHuds" />
    <div v-if="isLoading" class="empty-state">正在扫描 HUD…</div>
    <div v-else-if="huds.length === 0" class="empty-state">
      <AppIcon name="layers" />
      <b>还没有找到可用的 HUD</b>
      <span>点右上角“导入 HUD”，选择 HUD 的 zip 文件。</span>
    </div>
    <div v-else class="hud-list">
      <HudCard v-for="hud in huds" :key="hud.id" :hud="hud" @delete="deleteHud" />
    </div>
  </div>
</template>

<style scoped>
.hud-list { display: flex; flex-direction: column; gap: 12px; }
</style>
