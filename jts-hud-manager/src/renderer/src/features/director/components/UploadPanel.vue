<script setup lang="ts">
// 网站实时上传：开关 + 现在的上传情况
import { computed } from 'vue'
import type { IntegrationStatus } from '../../../composables/useDirectorStatus'
import { formatClock } from '../../../composables/useActivityLog'

const props = defineProps<{ integration: IntegrationStatus | null; cs2Fresh: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const enabled = computed(() => Boolean(props.integration?.forwardLiveData))
const state = computed(() => {
  const value = props.integration
  if (!value?.forwardLiveData) return { text: '未开启', tone: '' }
  if (value.forwardClosedMatchId) return { text: '比赛已结束，已停止', tone: 'warn' }
  if (!value.forwardTargetMatchId) return { text: '等待同步比赛', tone: 'warn' }
  if (Number(value.forwardAttempts) > 0) return { text: '正在重试', tone: 'warn' }
  return props.cs2Fresh ? { text: '正在上传', tone: 'good' } : { text: '等待 CS2 数据', tone: '' }
})
</script>

<template>
  <section class="panel dock-panel">
    <div class="panel-head">
      <b>网站实时上传</b>
      <button
        type="button"
        class="switch"
        :class="{ on: enabled }"
        role="switch"
        :aria-checked="enabled"
        :title="enabled ? '点击停止上传' : '点击开启上传'"
        @click="emit('toggle')"
      />
    </div>
    <div class="kv"><span>状态</span><b :class="state.tone">{{ state.text }}</b></div>
    <div class="kv"><span>上传目标</span><b class="num">{{ integration?.forwardTargetMatchId ? `#${integration.forwardTargetMatchId}` : '无' }}</b></div>
    <div class="kv"><span>重试次数</span><b class="num" :class="{ warn: Number(integration?.forwardAttempts) > 0 }">{{ integration?.forwardAttempts || 0 }}</b></div>
    <div class="kv"><span>待传单图结果</span><b class="num" :class="{ warn: Number(integration?.pendingResults) > 0 }">{{ integration?.pendingResults || 0 }}</b></div>
    <div class="kv"><span>最后收到 CS2</span><b class="num">{{ formatClock(integration?.lastLocalDataAt) }}</b></div>
  </section>
</template>

<style scoped>
.dock-panel { padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
.panel-head { margin-bottom: 2px; }
</style>
