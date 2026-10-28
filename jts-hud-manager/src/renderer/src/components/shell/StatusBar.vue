<script setup lang="ts">
// 底部状态栏：最近一次操作 + 端口 + 版本号
import { onMounted, ref } from 'vue'
import { port } from '../../index'
import { formatClock, useActivityLog } from '../../composables/useActivityLog'

const { latest } = useActivityLog()
const version = ref('')
const gsiPort = ref(23415)

onMounted(async () => {
  try {
    const info = await window.api?.getAppInfo?.()
    if (info) {
      version.value = info.version
      gsiPort.value = info.gsiPort
    }
  } catch {
    // 拿不到版本号时只是不显示，不影响使用
  }
})
</script>

<template>
  <footer class="statusbar">
    <span v-if="latest" class="last" :title="latest.text">
      <span class="dot" :class="latest.level" />
      <span class="num">{{ formatClock(latest.at) }}</span>
      <span class="last-text">{{ latest.text }}</span>
    </span>
    <span v-else class="last muted">就绪</span>
    <span class="meta num">GSI {{ gsiPort }} · HUD {{ port }}<template v-if="version"> · v{{ version }}</template></span>
  </footer>
</template>

<style scoped>
.statusbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 20px; background: var(--bg-panel); border-top: 1px solid var(--border); font-size: 12px; color: var(--text-3); }
.last { display: inline-flex; align-items: center; gap: 8px; min-width: 0; color: var(--text-2); }
.last .dot { box-shadow: none; }
.last-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.muted { color: var(--text-3); }
.meta { flex: none; }
</style>
