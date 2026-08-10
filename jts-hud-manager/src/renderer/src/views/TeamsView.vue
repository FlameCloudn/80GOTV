<script setup lang="ts">
import BaseModal from '../components/base/BaseModal.vue';
import BaseTable from '../components/base/BaseTable.vue';
import TeamForm from '../features/teams/components/TeamForm.vue';
import TeamsPageHeader from '../features/teams/components/TeamsPageHeader.vue';
import TeamsBulkBar from '../features/teams/components/TeamsBulkBar.vue';
import { useTeamsView } from '../features/teams/composables/useTeamsView';
import { API_URL } from '../index';

const {
  teams, players, isLoading, sortedTeams, tableHeaders,
  sortKey, sortDir, handleSort,
  selectedTeamIds, handleSelectionChange, handleDeleteSelected, handleDeleteAll,
  isModalOpen, isEditing, formData, handleSave, openCreateModal, openEditModal,
  exportTeams, importTeams, deleteTeam,
} = useTeamsView();

const baseUrl = API_URL.replace('/api', '');
</script>

<template>
  <div class="p-6 bg-surface text-zinc-200 min-h-screen relative">
    <TeamsPageHeader
      :teams-count="teams.length"
      @import="importTeams"
      @export="exportTeams(teams)"
      @delete-all="handleDeleteAll"
      @add="openCreateModal"
    />

    <TeamsBulkBar
      v-if="selectedTeamIds.length > 0"
      :selected-count="selectedTeamIds.length"
      @delete-selected="handleDeleteSelected"
    />

    <BaseTable
      :headers="tableHeaders"
      :items="sortedTeams"
      :is-loading="isLoading"
      :selectable="true"
      :sort-key="sortKey"
      :sort-dir="sortDir"
      search-placeholder="搜索战队..."
      @edit="openEditModal"
      @delete="deleteTeam"
      @sort="handleSort"
      @selection-change="handleSelectionChange"
    >
      <template #cell-logo="{ item }">
        <div class="size-12 flex items-center justify-center">
          <img v-if="item.logo" :src="`${baseUrl}${item.logo}`" class="w-full h-full object-contain" />
          <span v-else class="text-xs font-bold text-zinc-500">{{ item.shortName }}</span>
        </div>
      </template>
    </BaseTable>

    <BaseModal
      :is-open="isModalOpen"
      :title="isEditing ? '编辑战队' : '添加战队'"
      form-id="teamForm"
      max-width-class="max-w-2xl"
      @close="isModalOpen = false"
      @cancel="isModalOpen = false"
    >
      <TeamForm
        :initial-data="formData"
        :is-editing="isEditing"
        :players="players"
        @submit="handleSave"
      />
    </BaseModal>
  </div>
</template>
