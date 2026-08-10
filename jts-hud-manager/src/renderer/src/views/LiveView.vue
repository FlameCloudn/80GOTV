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

<template>
  <div class="p-6 bg-surface text-zinc-200 min-h-screen relative">
    <LivePageHeader :is-connected="isConnected" />

    <div v-if="!gameState" class="bg-zinc-800 p-12 rounded-xl border border-zinc-700 text-center flex flex-col items-center justify-center">
      <div class="size-6 border-4 border-zinc-600 border-t-primary rounded-full animate-spin"></div>
      <h3 class="text-xl font-bold text-text-main">正在等待 CS2 数据</h3>
      <p class="text-zinc-300 mt-1">请以观战者身份进入录像或比赛服务器。</p>
      <p class="text-zinc-500 text-sm mt-1 italic">如果一直没有数据，请到设置中检查 GSI 配置。</p>
    </div>

    <div v-else class="space-y-6">
      <LiveScoreboard
        :ct-score="gameState.map?.team_ct?.score || 0"
        :t-score="gameState.map?.team_t?.score || 0"
        :map-name="gameState.map?.name || '未知'"
        :phase-ends-in="gameState.phase_countdowns?.phase_ends_in || 0"
        :phase="gameState.phase_countdowns?.phase"
      />

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LivePlayerPanel
          side="CT"
          :players="ctPlayers"
          @edit="openEditModal"
          @add-all="openAddAllModal('CT')"
        />
        <LivePlayerPanel
          side="T"
          :players="tPlayers"
          @edit="openEditModal"
          @add-all="openAddAllModal('T')"
        />
      </div>
    </div>

    <LiveAddAllModal
      :is-open="isAddAllModalOpen"
      :side="addAllSide"
      :teams="availableTeams"
      :player-count="addAllSide === 'CT' ? ctPlayers.length : tPlayers.length"
      v-model:selected-team-id="selectedTeamForAddAll"
      :is-adding="isAddingAll"
      @close="isAddAllModalOpen = false"
      @confirm="handleAddAll"
    />

    <BaseModal
      :is-open="isModalOpen"
      :title="isEditing ? '更新选手资料' : '添加选手资料'"
      form-id="playerForm"
      @close="isModalOpen = false"
      @cancel="isModalOpen = false"
    >
      <PlayerForm
        :initial-data="formData"
        :teams="availableTeams"
        :is-editing="isEditing"
        :lock-steam-id="true"
        @submit="handleSave"
      />
    </BaseModal>
  </div>
</template>
