<script setup lang="ts">
// 选手：表格（可搜索、排序、多选删除）+ 添加 / 编辑弹窗
import BaseModal from '../components/base/BaseModal.vue'
import BaseTable from '../components/base/BaseTable.vue'
import TeamBadge from '../components/ui/TeamBadge.vue'
import PlayerForm from '../features/players/components/PlayerForm.vue'
import PlayersPageHeader from '../features/players/components/PlayersPageHeader.vue'
import PlayersBulkBar from '../features/players/components/PlayersBulkBar.vue'
import { usePlayersView } from '../features/players/composables/usePlayersView'
import { assetUrl, teamAbbr } from '../utils/display'

const {
  players, availableTeams, isPlayersLoading, sortedPlayers, teamMap, tableHeaders,
  sortKey, sortDir, handleSort,
  selectedPlayerIds, handleSelectionChange, handleDeleteSelected, handleDeleteAll,
  isModalOpen, isEditing, formData, handleSave, openCreateModal, openEditModal,
  exportPlayers, importPlayers, deletePlayer
} = usePlayersView()
</script>

<template>
  <div class="page">
    <PlayersPageHeader
      :players-count="players.length"
      @import="importPlayers"
      @export="exportPlayers(players)"
      @delete-all="handleDeleteAll"
      @add="openCreateModal"
    />
    <PlayersBulkBar v-if="selectedPlayerIds.length > 0" :selected-count="selectedPlayerIds.length" @delete-selected="handleDeleteSelected" />

    <BaseTable
      :headers="tableHeaders"
      :items="sortedPlayers"
      :is-loading="isPlayersLoading"
      :selectable="true"
      :sort-key="sortKey"
      :sort-dir="sortDir"
      search-placeholder="搜索昵称、姓名"
      @edit="openEditModal"
      @delete="deletePlayer"
      @sort="handleSort"
      @selection-change="handleSelectionChange"
    >
      <template #cell-avatar="{ item }">
        <span class="avatar">
          <img v-if="item.avatar" :src="assetUrl(item.avatar)" alt="" />
          <template v-else>{{ item.username?.slice(0, 1)?.toUpperCase() || '?' }}</template>
        </span>
      </template>
      <template #cell-username="{ item }">
        <div class="player-cell">
          <div class="player-line">
            <b>{{ item.username || '未命名选手' }}</b>
            <span v-if="item.isCoach" class="tag tag-bad">教练</span>
            <span v-if="item.country" class="tag">{{ item.country }}</span>
          </div>
          <small class="num">{{ item.steamid || '没有 Steam64 ID' }}</small>
        </div>
      </template>
      <template #cell-firstName="{ item }">{{ item.firstName || '—' }}</template>
      <template #cell-lastName="{ item }">{{ item.lastName || '—' }}</template>
      <template #cell-team="{ item }">
        <span v-if="teamMap[item.team]" class="team-cell">
          <TeamBadge :logo="assetUrl(teamMap[item.team].logo)" :abbr="teamAbbr(teamMap[item.team].name, teamMap[item.team].shortName)" size="sm" />
          {{ teamMap[item.team].name }}
        </span>
        <span v-else class="muted">未加入战队</span>
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
      <PlayerForm :initial-data="formData" :teams="availableTeams" :is-editing="isEditing" @submit="handleSave" />
    </BaseModal>
  </div>
</template>

<style scoped>
.avatar { width: 38px; height: 38px; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-md); background: var(--bg-raised); border: 1px solid var(--border); color: var(--text-3); font-weight: 700; }
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.player-cell { display: flex; flex-direction: column; gap: 2px; }
.player-line { display: flex; align-items: center; gap: 6px; }
.player-line b { color: var(--text); font-size: 14px; }
.player-cell small { font-size: 11px; color: var(--text-3); }
.team-cell { display: inline-flex; align-items: center; gap: 8px; color: var(--text-2); }
.muted { color: var(--text-3); font-size: 12px; }
</style>
