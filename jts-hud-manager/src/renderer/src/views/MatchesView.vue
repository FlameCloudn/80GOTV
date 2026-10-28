<script setup lang="ts">
// 比赛：一场一张卡片。当前比赛排最前、蓝框 + “当前比赛”。
import AppIcon from '../components/ui/AppIcon.vue'
import TeamBadge from '../components/ui/TeamBadge.vue'
import MatchesPageHeader from '../features/matches/components/MatchesPageHeader.vue'
import { useMatchesView } from '../features/matches/composables/useMatchesView'

const { isLoading, filter, search, counts, visibleCards, deleteMatch, toggleCurrent, openEdit, openCreate } = useMatchesView()
</script>

<template>
  <div class="page">
    <MatchesPageHeader v-model:filter="filter" v-model:search="search" :counts="counts" @create="openCreate" />

    <div v-if="isLoading && !visibleCards.length" class="empty-state">正在读取比赛…</div>
    <div v-else-if="!visibleCards.length" class="empty-state">
      <AppIcon name="calendar" />
      <b>{{ counts.all ? '没有符合条件的比赛' : '还没有比赛' }}</b>
      <span>{{ counts.all ? '换个筛选或搜索词试试。' : '在「导播台」同步网站比赛，或点右上角“创建比赛”。' }}</span>
    </div>

    <div v-else class="cards">
      <article v-for="card in visibleCards" :key="card.id" class="panel match-card" :class="{ current: card.current }">
        <header class="card-head">
          <span class="source">
            <AppIcon :name="card.websiteId ? 'link' : 'edit'" />{{ card.websiteId ? `网站 #${card.websiteId}` : '手动创建' }}
          </span>
          <span class="tag">{{ card.bo }}</span>
          <span v-if="card.current" class="current-tag"><AppIcon name="star" />当前比赛</span>
        </header>

        <div class="teams">
          <div v-for="side in [card.left, card.right]" :key="side === card.left ? 'left' : 'right'" class="team-row" :class="{ tbd: side.tbd }">
            <TeamBadge :logo="side.logo" :abbr="side.abbr" size="sm" />
            <span class="team-name">{{ side.name }}</span>
            <span class="score num" :class="{ lead: side.wins > (side === card.left ? card.right.wins : card.left.wins) }">{{ side.wins }}</span>
          </div>
        </div>

        <div class="maps">
          <span v-for="map in card.maps" :key="map.key" class="chip" :class="map.state">{{ map.name }}<b v-if="map.score">{{ map.score }}</b></span>
          <span v-if="!card.maps.length" class="hint">还没设置地图</span>
        </div>

        <footer class="card-foot">
          <button type="button" class="btn btn-sm" :class="{ 'btn-danger': card.current }" @click="toggleCurrent(card.raw)">
            <AppIcon :name="card.current ? 'x' : 'star'" />{{ card.current ? '停止当前' : '设为当前' }}
          </button>
          <span class="spacer" />
          <button type="button" class="icon-btn" title="编辑比赛" @click="openEdit(card)"><AppIcon name="edit" /></button>
          <button type="button" class="icon-btn danger" title="删除比赛" @click="deleteMatch(card.id)"><AppIcon name="trash" /></button>
        </footer>
      </article>
    </div>
  </div>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.match-card { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.match-card.current { border: 2px solid var(--accent); padding: 13px 15px; box-shadow: 0 0 0 4px var(--accent-soft); }
.card-head { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); }
.source { display: inline-flex; align-items: center; gap: 6px; margin-right: auto; }
.source .icon { width: 14px; height: 14px; color: var(--text-3); }
.current-tag { height: 20px; display: inline-flex; align-items: center; gap: 5px; padding: 0 7px; border-radius: var(--radius-sm); background: var(--gold-soft); color: var(--gold); font-size: 11px; font-weight: 700; }
.current-tag .icon { width: 12px; height: 12px; fill: currentColor; }
.teams { display: flex; flex-direction: column; gap: 8px; }
.team-row { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600; }
.team-row.tbd { color: var(--text-3); font-weight: 500; }
.team-name { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.score { margin-left: auto; width: 24px; text-align: center; font-size: 18px; font-weight: 800; }
.score.lead { color: var(--green); }
.maps { display: flex; flex-wrap: wrap; gap: 6px; min-height: 24px; align-items: center; }
.card-foot { display: flex; align-items: center; gap: 6px; padding-top: 12px; border-top: 1px solid var(--border); }
.spacer { flex: 1; }
</style>
