<script setup lang="ts">
import { useHudPanelView } from '../features/huds/composables/useHudPanelView';
import HudPanelHeader from '../features/huds/components/HudPanelHeader.vue';
import HudPanelTabBar from '../features/huds/components/HudPanelTabBar.vue';
import HudPanelSection from '../features/huds/components/HudPanelSection.vue';

const {
  hudId,
  teams,
  matches,
  panel,
  config,
  sectionStatus,
  activeTab,
  activeSection,
  livePlayerSteamIds,
  showOnlyActivePlayers,
  playersForSection,
  saveSectionConfig,
  fireAction,
  uploadImage,
  clearImage,
  uploadImageToList,
  removeImageFromList,
} = useHudPanelView();
</script>

<template>
  <div class="page">
    <HudPanelHeader :hud-id="hudId" />
    <HudPanelTabBar v-if="panel.length > 0" v-model:active-tab="activeTab" :sections="panel" />
    <div v-if="panel.length === 0" class="empty-state">这个 HUD 没有提供控制面板配置（panel.json）。</div>
    <div v-else-if="activeSection.name && config[activeSection.name]" class="panel-wrap">
      <HudPanelSection
        :section="activeSection"
        :section-config="config[activeSection.name]"
        :teams="teams"
        :players="playersForSection(activeSection.name)"
        :matches="matches"
        :show-only-active-players="showOnlyActivePlayers[activeSection.name] ?? false"
        :live-data-available="livePlayerSteamIds.size > 0"
        :status="sectionStatus[activeSection.name]"
        @save="saveSectionConfig(activeSection.name)"
        @fire-action="(name, val) => fireAction(name, val)"
        @upload-image="(inputName, file) => uploadImage(activeSection.name, inputName, file)"
        @clear-image="(inputName) => clearImage(activeSection.name, inputName)"
        @upload-image-to-list="(inputName, file) => uploadImageToList(activeSection.name, inputName, file)"
        @remove-image-from-list="(inputName, url) => removeImageFromList(activeSection.name, inputName, url)"
        @toggle-active-players="showOnlyActivePlayers[activeSection.name] = !showOnlyActivePlayers[activeSection.name]"
      />
    </div>
  </div>
</template>

<style scoped>
.panel-wrap { width: 100%; max-width: 920px; margin: 0 auto; }
</style>
