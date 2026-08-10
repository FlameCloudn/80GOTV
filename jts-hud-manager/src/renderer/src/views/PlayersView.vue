<script setup lang="ts">
import BaseModal from '../components/base/BaseModal.vue';
import BaseTable from '../components/base/BaseTable.vue';
import BaseBadge from '../components/base/BaseBadge.vue';
import PlayerForm from '../features/players/components/PlayerForm.vue';
import PlayersPageHeader from '../features/players/components/PlayersPageHeader.vue';
import PlayersBulkBar from '../features/players/components/PlayersBulkBar.vue';
import { usePlayersView } from '../features/players/composables/usePlayersView';
import { API_URL } from '../index';

const {
  players, availableTeams, isPlayersLoading, sortedPlayers, teamMap, tableHeaders,
  sortKey, sortDir, handleSort,
  selectedPlayerIds, handleSelectionChange, handleDeleteSelected, handleDeleteAll,
  isModalOpen, isEditing, formData, handleSave, openCreateModal, openEditModal,
  exportPlayers, importPlayers, deletePlayer,
} = usePlayersView();

const baseUrl = API_URL.replace('/api', '');

</script>

<template>
  <div class="p-6 bg-surface text-zinc-200 min-h-screen">
    <PlayersPageHeader
      :players-count="players.length"
      @import="importPlayers"
      @export="exportPlayers(players)"
      @delete-all="handleDeleteAll"
      @add="openCreateModal"
    />

    <PlayersBulkBar
      v-if="selectedPlayerIds.length > 0"
      :selected-count="selectedPlayerIds.length"
      @delete-selected="handleDeleteSelected"
    />

    <BaseTable
      :headers="tableHeaders"
      :items="sortedPlayers"
      :is-loading="isPlayersLoading"
      :selectable="true"
      :sort-key="sortKey"
      :sort-dir="sortDir"
      @edit="openEditModal"
      @delete="deletePlayer"
      @sort="handleSort"
      @selection-change="handleSelectionChange"
    >
      <template #cell-avatar="{ item }">
        <div class="size-14">
          <img v-if="item.avatar" :src="`${baseUrl}${item.avatar}`" class="size-12 object-cover" />
        </div>
      </template>

      <template #cell-username="{ item }">
        <div class="font-bold text-text-main flex items-center gap-2">
          {{ item.username }}
          <BaseBadge v-if="item.isCoach" variant="red">教练</BaseBadge>
          <BaseBadge v-if="item.country">{{ item.country }}</BaseBadge>
        </div>
      </template>

      <template #cell-team="{ item }">
        <div v-if="teamMap[item.team]" class="flex items-center gap-2.5">
          <div class="size-10 flex items-center justify-center overflow-hidden shrink-0">
            <img v-if="teamMap[item.team].logo" :src="`${baseUrl}${teamMap[item.team].logo}`" class="w-full h-full object-contain" />
            <span v-else class="text-xs font-bold text-zinc-500">{{ teamMap[item.team].shortName }}</span>
          </div>
        </div>
        <span v-else class="text-zinc-600 italic text-xs">未加入战队</span>
      </template>
    </BaseTable>

    <BaseModal
      :is-open="isModalOpen"
      :title="isEditing ? '编辑选手' : '添加选手'"
      form-id="playerForm"
      max-width-class="max-w-xl"
      @close="isModalOpen = false"
      @cancel="isModalOpen = false"
    >
      <PlayerForm
        :initial-data="formData"
        :teams="availableTeams"
        :is-editing="isEditing"
        @submit="handleSave"
      />
    </BaseModal>
  </div>
</template>
