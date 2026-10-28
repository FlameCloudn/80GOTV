<script setup lang="ts">
// 最近操作：切换场景、同步、检查连接、出错都记在这里（最新的在最上面）
import { formatClock, useActivityLog } from '../../../composables/useActivityLog'

const { entries } = useActivityLog()
</script>

<template>
  <section class="panel log">
    <div class="log-head"><span class="kicker">最近操作</span></div>
    <p v-if="!entries.length" class="log-empty">还没有操作。切换场景、同步比赛、检查连接后会记在这里。</p>
    <ul v-else class="log-list">
      <li v-for="entry in entries" :key="entry.id" :title="entry.text">
        <span class="num log-time">{{ formatClock(entry.at) }}</span>
        <span class="dot" :class="entry.level" />
        <span class="log-text">{{ entry.text }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.log { display: flex; flex-direction: column; min-height: 0; padding: 10px 14px 6px; }
.log-head { padding-bottom: 6px; }
.log-empty { font-size: 12px; color: var(--text-3); padding: 8px 0; }
.log-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; min-height: 0; }
.log-list li { display: flex; align-items: center; gap: 10px; height: 28px; border-top: 1px solid var(--border); font-size: 13px; color: var(--text-2); }
.log-time { width: 62px; flex: none; font-size: 12px; color: var(--text-3); }
.log-list .dot { box-shadow: none; }
.log-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
