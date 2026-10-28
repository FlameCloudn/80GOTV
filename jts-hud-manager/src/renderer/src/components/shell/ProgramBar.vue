<script setup lang="ts">
// 顶部节目条（每个页面都在）：正在输出的画面、比分、四个连接灯、时钟
import { computed } from 'vue'
import TeamBadge from '../ui/TeamBadge.vue'
import { useDirectorStatus } from '../../composables/useDirectorStatus'
import { formatDuration, mapLabel } from '../../utils/display'

const {
  director, sceneSince, now, seriesTeams, currentMatch, currentBo, liveGame, lastSocketUpdate,
  cs2Fresh, apiOnline, websiteConfirmed, selectedMatch, activeSceneLabel
} = useDirectorStatus()

const onAirFor = computed(() => formatDuration(now.value - sceneSince.value))
const liveFresh = computed(() => Boolean(lastSocketUpdate.value && now.value - lastSocketUpdate.value <= 5000))

const PHASE_LABELS: Record<string, string> = { warmup: '热身', intermission: '换边休息', gameover: '本图结束' }
const mapInfo = computed(() => {
  const game = liveGame.value
  if (!game || !liveFresh.value) return null
  const phase = PHASE_LABELS[game.mapPhase] || `第 ${game.round + 1} 回合`
  return { name: mapLabel(game.mapName), phase, ct: game.ctScore, t: game.tScore }
})

type Light = { label: string; state: 'ok' | 'warn' | 'bad' | 'idle'; title: string }
const lights = computed<Light[]>(() => {
  const clients = director.value.hudClients
  const website: Light = websiteConfirmed.value
    ? { label: '网站', state: 'ok', title: '网站连接检查通过' }
    : selectedMatch.value
      ? { label: '网站', state: 'warn', title: '已选网站比赛，还没检查连接' }
      : { label: '网站', state: 'idle', title: '还没选网站比赛' }
  return [
    { label: '服务', state: apiOnline.value ? 'ok' : 'bad', title: apiOnline.value ? '导播服务正常' : '导播服务没有启动' },
    { label: 'CS2', state: cs2Fresh.value ? 'ok' : 'idle', title: cs2Fresh.value ? '正在接收 CS2 数据' : '等待 CS2 数据（以观战者身份进服后才有）' },
    website,
    { label: clients > 0 ? `OBS×${clients}` : 'OBS', state: clients > 0 ? 'ok' : 'warn', title: clients > 0 ? `${clients} 个画面在线` : '没有画面连接（OBS 浏览器源还没打开）' }
  ]
})

const clock = computed(() => new Date(now.value).toLocaleTimeString('zh-CN', { hour12: false }))
const left = computed(() => seriesTeams.value.left)
const right = computed(() => seriesTeams.value.right)
</script>

<template>
  <header class="program">
    <div class="pgm" :class="director.visible ? 'on' : 'off'" :title="director.visible ? '直播画面正在显示 HUD' : 'HUD 已全部隐藏，观众只看到纯游戏画面'">
      <span class="pgm-tag">{{ director.visible ? 'ON AIR' : '已隐藏' }}</span>
      <div class="pgm-text"><small>当前输出</small><b>{{ activeSceneLabel }}</b></div>
      <span class="pgm-time num" title="切到这个画面后过了多久">{{ onAirFor }}</span>
    </div>

    <div v-if="currentMatch" class="board">
      <div class="board-team">
        <TeamBadge :logo="left.logo" :abbr="left.abbr" size="sm" />
        <b class="board-name" :title="left.name">{{ left.name }}</b>
        <span class="series-box num" :class="{ lead: left.wins > right.wins }">{{ left.wins }}</span>
      </div>
      <div class="board-map">
        <template v-if="mapInfo">
          <span class="map-score num"><i class="ct">CT</i>{{ mapInfo.ct }}<em>:</em>{{ mapInfo.t }}<i class="t">T</i></span>
          <small>{{ mapInfo.name }} · {{ mapInfo.phase }}</small>
        </template>
        <template v-else>
          <span class="map-bo num">{{ currentBo }}</span>
          <small>等待比赛数据</small>
        </template>
      </div>
      <div class="board-team right">
        <span class="series-box num" :class="{ lead: right.wins > left.wins }">{{ right.wins }}</span>
        <b class="board-name" :title="right.name">{{ right.name }}</b>
        <TeamBadge :logo="right.logo" :abbr="right.abbr" size="sm" />
      </div>
    </div>
    <div v-else class="board board-empty">还没有当前比赛 · 在「导播台」同步网站比赛，或在「比赛」页设为当前</div>

    <div class="lights">
      <span v-for="light in lights" :key="light.label" class="light" :title="light.title">
        <span class="dot" :class="light.state" />{{ light.label }}
      </span>
    </div>
    <span class="clock num">{{ clock }}</span>
  </header>
</template>

<style scoped>
.program { display: grid; grid-template-columns: 250px minmax(0, 1fr) auto auto; align-items: center; gap: 18px; padding: 0 20px; background: var(--bg-panel); border-bottom: 1px solid var(--border); }
.pgm { display: flex; align-items: center; gap: 10px; height: 44px; padding: 0 12px 0 6px; border-radius: var(--radius-md); min-width: 0; }
.pgm.on { background: linear-gradient(90deg, rgba(239, 91, 82, 0.24), rgba(239, 91, 82, 0.06)); border: 1px solid rgba(239, 91, 82, 0.5); }
.pgm.off { background: var(--bg-raised); border: 1px solid var(--border-strong); }
.pgm-tag { flex: none; padding: 8px 7px; border-radius: var(--radius-sm); font: 800 11px/1 'Montserrat', 'Microsoft YaHei UI', sans-serif; letter-spacing: 0.06em; }
.on .pgm-tag { background: var(--live); color: #fff; }
.off .pgm-tag { background: var(--bg-hover); color: var(--text-2); }
.pgm-text { min-width: 0; line-height: 1.25; }
.pgm-text small { display: block; font-size: 11px; }
.pgm-text b { display: block; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.on .pgm-text small { color: #f0a39c; }
.on .pgm-text b { color: #fff; }
.off .pgm-text small { color: var(--text-3); }
.pgm-time { margin-left: auto; font-weight: 600; }
.on .pgm-time { color: #ffd2ce; }
.off .pgm-time { color: var(--text-3); }

.board { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 14px; min-width: 0; }
.board-empty { display: block; text-align: center; font-size: 12px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.board-team { display: flex; align-items: center; justify-content: flex-end; gap: 9px; min-width: 0; }
.board-team.right { justify-content: flex-start; }
.board-name { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.series-box { flex: none; width: 28px; height: 28px; display: grid; place-items: center; border-radius: var(--radius-md); background: var(--bg-raised); border: 1px solid var(--border-strong); font-size: 15px; font-weight: 800; }
.series-box.lead { color: var(--green); border-color: rgba(76, 174, 124, 0.5); }
.board-map { display: flex; flex-direction: column; align-items: center; line-height: 1.2; min-width: 96px; }
.map-score { display: inline-flex; align-items: baseline; gap: 6px; font-size: 20px; font-weight: 800; }
.map-score em { font-style: normal; color: var(--text-3); font-weight: 600; }
.map-score i { font-style: normal; font-size: 10px; font-weight: 800; }
.map-score .ct { color: var(--ct); }
.map-score .t { color: var(--t); }
.map-bo { font-size: 16px; font-weight: 800; color: var(--text-2); }
.board-map small { font-size: 11px; color: var(--text-3); white-space: nowrap; }

.lights { display: flex; align-items: center; gap: 13px; }
.light { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); white-space: nowrap; cursor: default; }
.clock { font-size: 16px; font-weight: 600; }
</style>
