<script setup lang="ts">
// 实时比分：CT 比分 | 地图、倒计时、阶段 | T 比分
import { mapLabel } from '../../../utils/display'

defineProps<{
  ctScore: number
  tScore: number
  mapName: string
  phaseEndsIn: number | string | undefined
  phase: string | undefined
}>()

const formatTime = (seconds: number | string | undefined): string => {
  const value = parseFloat(String(seconds))
  if (!Number.isFinite(value)) return '0:00'
  const remaining = Math.max(0, Math.ceil(value))
  return `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`
}

const PHASE_LABELS: Record<string, string> = {
  freezetime: '准备时间',
  live: '进行中',
  over: '回合结束',
  paused: '已暂停',
  timeout_ct: 'CT 暂停',
  timeout_t: 'T 暂停',
  bomb: '炸弹已安放',
  defuse: '正在拆弹',
  warmup: '热身'
}
const formatPhase = (phase: string | undefined) => (phase ? PHASE_LABELS[phase] ?? phase : '等待中')
</script>

<template>
  <section class="panel scoreboard">
    <div class="side ct"><span class="side-label">CT</span><span class="side-score num">{{ ctScore }}</span></div>
    <div class="center">
      <span class="map num">{{ mapLabel(mapName) || '未知地图' }}</span>
      <span class="clock num">{{ formatTime(phaseEndsIn) }}</span>
      <span class="phase">{{ formatPhase(phase) }}</span>
    </div>
    <div class="side t"><span class="side-score num">{{ tScore }}</span><span class="side-label">T</span></div>
  </section>
</template>

<style scoped>
.scoreboard { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; overflow: hidden; }
.side { display: flex; align-items: center; gap: 16px; height: 96px; padding: 0 28px; }
.side.ct { justify-content: flex-start; background: linear-gradient(90deg, var(--ct-soft), transparent); box-shadow: inset 4px 0 0 var(--ct); }
.side.t { justify-content: flex-end; background: linear-gradient(270deg, var(--t-soft), transparent); box-shadow: inset -4px 0 0 var(--t); }
.side-label { font: 800 14px/1 'Montserrat', sans-serif; letter-spacing: 0.08em; }
.ct .side-label { color: var(--ct); }
.t .side-label { color: var(--t); }
.side-score { font-size: 46px; font-weight: 800; line-height: 1; }
.center { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 0 36px; border-left: 1px solid var(--border); border-right: 1px solid var(--border); height: 96px; justify-content: center; }
.map { font-size: 12px; font-weight: 700; color: var(--text-3); letter-spacing: 0.06em; text-transform: uppercase; }
.clock { font-size: 30px; font-weight: 700; }
.phase { font-size: 12px; color: var(--text-2); }
</style>
