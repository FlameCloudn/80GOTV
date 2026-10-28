<script setup lang="ts">
// 一边（CT 或 T）的选手：名字、是否已录入、击杀 / 死亡 / 助攻；可编辑、可整队加入战队
import AppIcon from '../../../components/ui/AppIcon.vue'
import type { GsiPlayer } from '../composables/useLiveView'

defineProps<{ side: 'CT' | 'T'; players: GsiPlayer[] }>()
const emit = defineEmits<{ edit: [player: GsiPlayer]; addAll: [] }>()
</script>

<template>
  <section class="panel side-panel" :class="side.toLowerCase()">
    <header class="side-head">
      <span class="side-name">{{ side }}</span>
      <span class="hint num">{{ players.length }} 名选手</span>
      <button type="button" class="btn btn-sm" :disabled="!players.length" @click="emit('addAll')"><AppIcon name="users" />全部加入战队</button>
    </header>
    <p v-if="!players.length" class="side-empty">这一边还没有选手。</p>
    <div v-for="player in players" :key="player.steamid" class="player-row" :class="{ coach: player.isCoach }">
      <div class="player-main">
        <div class="player-line">
          <b>{{ player.name }}</b>
          <span v-if="player.isCoach" class="tag tag-bad">教练</span>
          <span v-else-if="player.inDB" class="tag tag-ok">已录入</span>
          <span v-else class="tag tag-warn">未录入</span>
        </div>
        <small class="num">{{ player.steamid }}</small>
      </div>
      <span class="kda num" title="击杀 / 死亡 / 助攻">
        {{ player.stats?.kills || 0 }}<i>/</i>{{ player.stats?.deaths || 0 }}<i>/</i>{{ player.stats?.assists || 0 }}
      </span>
      <button type="button" class="btn btn-sm" @click="emit('edit', player)">
        <AppIcon :name="player.inDB ? 'edit' : 'plus'" />{{ player.inDB ? '编辑' : '录入' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.side-panel { overflow: hidden; }
.side-head { display: flex; align-items: center; gap: 10px; padding: 10px 12px 10px 16px; border-bottom: 1px solid var(--border); }
.ct .side-head { background: linear-gradient(90deg, var(--ct-soft), transparent 70%); box-shadow: inset 3px 0 0 var(--ct); }
.t .side-head { background: linear-gradient(90deg, var(--t-soft), transparent 70%); box-shadow: inset 3px 0 0 var(--t); }
.side-name { font: 800 14px/1 'Montserrat', sans-serif; letter-spacing: 0.06em; }
.ct .side-name { color: var(--ct); }
.t .side-name { color: var(--t); }
.side-head .btn { margin-left: auto; }
.side-empty { padding: 20px 16px; font-size: 13px; color: var(--text-3); }
.player-row { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 8px 12px 8px 16px; border-bottom: 1px solid var(--border); }
.player-row:last-child { border-bottom: none; }
.player-row:hover { background: var(--bg-hover); }
.player-row.coach { background: rgba(239, 91, 82, 0.06); }
.player-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.player-line { display: flex; align-items: center; gap: 6px; }
.player-line b { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.player-main small { font-size: 11px; color: var(--text-3); }
.kda { font-size: 14px; font-weight: 700; color: var(--text); }
.kda i { font-style: normal; margin: 0 3px; color: var(--text-3); font-weight: 500; }
</style>
