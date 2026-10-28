<script setup lang="ts">
// 战队：表格（可搜索、排序、多选删除）+ 添加 / 编辑弹窗
import BaseModal from '../components/base/BaseModal.vue'
import BaseTable from '../components/base/BaseTable.vue'
import TeamBadge from '../components/ui/TeamBadge.vue'
import TeamForm from '../features/teams/components/TeamForm.vue'
import TeamsPageHeader from '../features/teams/components/TeamsPageHeader.vue'
import TeamsBulkBar from '../features/teams/components/TeamsBulkBar.vue'
import { useTeamsView } from '../features/teams/composables/useTeamsView'
import { countryOptions } from '../utils/countries'
import { assetUrl, teamAbbr } from '../utils/display'

const {
  teams, players, isLoading, sortedTeams, tableHeaders,
  sortKey, sortDir, handleSort,
  selectedTeamIds, handleSelectionChange, handleDeleteSelected, handleDeleteAll,
  isModalOpen, isEditing, formData, handleSave, openCreateModal, openEditModal,
  exportTeams, importTeams, deleteTeam
} = useTeamsView()

const playerCount = (teamId: string) => players.value.filter((player) => player.team === teamId).length
const countryName = (code: string) => countryOptions.find((country) => country.code === code)?.name || code || '—'
</script>

<template>
  <div class="page">
    <TeamsPageHeader
      :teams-count="teams.length"
      @import="importTeams"
      @export="exportTeams(teams)"
      @delete-all="handleDeleteAll"
      @add="openCreateModal"
    />
    <TeamsBulkBar v-if="selectedTeamIds.length > 0" :selected-count="selectedTeamIds.length" @delete-selected="handleDeleteSelected" />

    <BaseTable
      :headers="tableHeaders"
      :items="sortedTeams"
      :is-loading="isLoading"
      :selectable="true"
      :sort-key="sortKey"
      :sort-dir="sortDir"
      search-placeholder="搜索战队名称或简称"
      @edit="openEditModal"
      @delete="deleteTeam"
      @sort="handleSort"
      @selection-change="handleSelectionChange"
    >
      <template #cell-logo="{ item }">
        <TeamBadge :logo="assetUrl(item.logo)" :abbr="teamAbbr(item.name, item.shortName)" />
      </template>
      <template #cell-name="{ item }">
        <b class="team-name">{{ item.name || '未命名战队' }}</b>
      </template>
      <template #cell-shortName="{ item }">
        <span class="num">{{ item.shortName || '—' }}</span>
      </template>
      <template #cell-country="{ item }">{{ countryName(item.country) }}</template>
      <template #cell-players="{ item }">
        <span class="num" :class="{ muted: !playerCount(item._id) }">{{ playerCount(item._id) }} 人</span>
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
      <TeamForm :initial-data="formData" :is-editing="isEditing" :players="players" @submit="handleSave" />
    </BaseModal>
  </div>
</template>

<style scoped>
.team-name { color: var(--text); font-size: 14px; }
.muted { color: var(--text-3); }
</style>
