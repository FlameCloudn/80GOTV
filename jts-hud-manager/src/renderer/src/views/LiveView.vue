<template>
  <div class="page">
    <LivePageHeader :is-connected="isConnected" />

    <div v-if="!gameState" class="empty-state waiting">
      <span class="spinner" />
      <b>正在等待 CS2 数据</b>
      <span>请以观战者身份进入录像或比赛服务器。</span>
      <span class="hint">一直没有数据时，到左下角「设置」里检查 GSI 配置。</span>
    </div>

    <template v-else>
      <LiveScoreboard
        :ct-score="gameState.map?.team_ct?.score || 0"
        :t-score="gameState.map?.team_t?.score || 0"
        :map-name="gameState.map?.name || ''"
        :phase-ends-in="gameState.phase_countdowns?.phase_ends_in || 0"
        :phase="gameState.phase_countdowns?.phase"
      />
      <div class="sides">
        <LivePlayerPanel side="CT" :players="ctPlayers" @edit="openEditModal" @add-all="openAddAllModal('CT')" />
        <LivePlayerPanel side="T" :players="tPlayers" @edit="openEditModal" @add-all="openAddAllModal('T')" />
      </div>
    </template>

    <LiveAddAllModal
      v-model:selected-team-id="selectedTeamForAddAll"
      :is-open="isAddAllModalOpen"
      :side="addAllSide"
      :teams="availableTeams"
      :player-count="addAllSide === 'CT' ? ctPlayers.length : tPlayers.length"
      :is-adding="isAddingAll"
      @close="isAddAllModalOpen = false"
      @confirm="handleAddAll"
    />
    <BaseModal
      :is-open="isModalOpen"
      :title="isEditing ? '更新选手资料' : '添加选手资料'"
      form-id="playerForm"
      max-width-class="max-w-xl"
      @close="isModalOpen = false"
      @cancel="isModalOpen = false"
    >
      <PlayerForm :initial-data="formData" :teams="availableTeams" :is-editing="isEditing" :lock-steam-id="true" @submit="handleSave" />
    </BaseModal>
  </div>
</template>

<script setup lang="ts">
import BaseModal from '../components/base/BaseModal.vue';
import PlayerForm from '../features/players/components/PlayerForm.vue';
import { useLiveView } from '../features/live/composables/useLiveView';
import LivePageHeader from '../features/live/components/LivePageHeader.vue';
import LiveScoreboard from '../features/live/components/LiveScoreboard.vue';
import LivePlayerPanel from '../features/live/components/LivePlayerPanel.vue';
import LiveAddAllModal from '../features/live/components/LiveAddAllModal.vue';

const {
  isConnected,
  gameState,
  ctPlayers,
  tPlayers,
  availableTeams,
  isModalOpen,
  isEditing,
  formData,
  handleSave,
  openEditModal,
  isAddAllModalOpen,
  addAllSide,
  selectedTeamForAddAll,
  isAddingAll,
  openAddAllModal,
  handleAddAll,
} = useLiveView();
</script>

<style scoped>
.waiting { min-height: 220px; }
.spinner { width: 26px; height: 26px; border-radius: 50%; border: 3px solid var(--border-strong); border-top-color: var(--accent); animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.sides { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
</style>
