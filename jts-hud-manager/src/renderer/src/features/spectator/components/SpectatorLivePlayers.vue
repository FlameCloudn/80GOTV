<script setup lang="ts">
// 当前比赛选手：点一下放进第一个空的数字键
import type { LivePlayer } from '../composables/useSpectator'

defineProps<{ gameState: any; livePlayers: LivePlayer[]; ctPlayers: LivePlayer[]; tPlayers: LivePlayer[] }>()
defineEmits<{ (e: 'quick-assign', name: string): void }>()

const slotText = (slot: number) => (slot === 0 ? '10' : String(slot))
</script>

<template>
  <section class="panel panel-pad">
    <div class="panel-head">
      <b>当前比赛选手</b>
      <span v-if="livePlayers.length" class="hint">点选手 → 放进第一个空的数字键</span>
    </div>
    <div v-if="!gameState" class="empty-state compact">
      <b>正在等待 CS2 数据</b>
      <span>请以观战者身份进入录像或比赛服务器。一直没有数据时，到「设置」里检查 GSI 配置。</span>
    </div>
    <div v-else-if="livePlayers.length === 0" class="empty-state compact">当前比赛中没有选手。</div>
    <div v-else class="sides">
      <div v-for="group in [{ side: 'CT', list: ctPlayers }, { side: 'T', list: tPlayers }]" :key="group.side" class="side" :class="group.side.toLowerCase()">
        <div class="side-label">{{ group.side }}</div>
        <div class="side-grid">
          <button v-for="player in group.list" :key="player.steamid" type="button" class="player-btn" title="放进第一个空的数字键" @click="$emit('quick-assign', player.name)">
            <span class="player-name">{{ player.name }}</span>
            <span class="player-slot num">位置 {{ slotText(player.observerSlot) }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.compact { margin-top: 12px; padding: 22px 16px; }
.sides { margin-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.side-label { margin-bottom: 6px; font: 800 12px/1 'Montserrat', sans-serif; letter-spacing: 0.08em; }
.ct .side-label { color: var(--ct); }
.t .side-label { color: var(--t); }
.side-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.player-btn { display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 10px; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--bg-raised); color: var(--text); text-align: left; }
.ct .player-btn { box-shadow: inset 3px 0 0 var(--ct); }
.t .player-btn { box-shadow: inset 3px 0 0 var(--t); }
.player-btn:hover { background: var(--bg-hover); border-color: var(--border-strong); }
.player-name { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.player-slot { flex: none; font-size: 11px; color: var(--text-3); }
</style>
