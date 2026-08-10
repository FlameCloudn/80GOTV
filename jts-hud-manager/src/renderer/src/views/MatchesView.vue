<script setup lang="ts">
import BaseTable from '../components/base/BaseTable.vue';
import BaseBadge from '../components/base/BaseBadge.vue';
import MatchesPageHeader from '../features/matches/components/MatchesPageHeader.vue';
import { useMatchesView } from '../features/matches/composables/useMatchesView';
import { API_URL } from '../index';
import BaseButton from '@renderer/components/base/BaseButton.vue';

const {
  matches, isLoading, tableHeaders,
  getTeamLogo, deleteMatch, toggleCurrent,
  openEdit, openCreate,
} = useMatchesView();

const baseUrl = API_URL.replace('/api', '');
</script>

<template>
  <div class="p-6 bg-surface text-zinc-200 min-h-screen relative">
    <MatchesPageHeader @create="openCreate" />

    <BaseTable
      :headers="tableHeaders"
      :items="matches"
      :is-loading="isLoading"
      @edit="openEdit"
      @delete="deleteMatch"
    >
      <template #row-actions="{ item }">
        <span v-if="item.current" class="text-xs font-bold text-blue-400 flex items-center gap-1.5 mr-1">
          <span class="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse"></span> 直播中
        </span>
        <BaseButton
          @click.stop="toggleCurrent(item)"
          size="sm"
          :variant="item.current
            ? 'danger'
            : 'secondary'"
        >
          <svg v-if="item.current" xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4.75a.75.75 0 0 0-1.125.65v13.2a.75.75 0 0 0 1.125.65l10.5-6.6a.75.75 0 0 0 0-1.3L6 4.75Z"/></svg>
          {{ item.current ? '停止' : '设为当前比赛' }}
        </BaseButton>
      </template>

      <template #cell-matchType="{ item }">
        <BaseBadge>{{ item.matchType }}</BaseBadge>
      </template>

      <template #cell-matchup="{ item }">
        <div class="flex items-center gap-3">
          <div class="size-10 flex items-center justify-center shrink-0">
            <img v-if="getTeamLogo(item.left.id)" :src="`${baseUrl}${getTeamLogo(item.left.id)}`" class="w-full h-full object-contain" />
          </div>
          <span class="text-zinc-400 text-lg">对阵</span>
          <div class="size-10 flex items-center justify-center shrink-0">
            <img v-if="getTeamLogo(item.right.id)" :src="`${baseUrl}${getTeamLogo(item.right.id)}`" class="w-full h-full object-contain" />
          </div>
        </div>
      </template>

      <template #cell-score="{ item }">
        <div class="bg-surface px-3 py-1 rounded border border-zinc-700 text-text-main inline-block">
          {{ item.left.wins }} - {{ item.right.wins }}
        </div>
      </template>
    </BaseTable>
  </div>
</template>
