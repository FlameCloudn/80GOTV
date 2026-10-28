<script setup lang="ts">
// 网站比赛：选比赛 → 同步比赛资料 → 检查完整连接
import AppIcon from '../../../components/ui/AppIcon.vue'
import type { WebsiteMatchOption } from '../composables/useDirectorActions'

defineProps<{
  matches: WebsiteMatchOption[]
  selected: string
  listBusy: boolean
  syncBusy: boolean
  checkBusy: boolean
  canCheck: boolean
  lastConfirmed: string
  confirmedFresh: boolean
}>()
const emit = defineEmits<{ choose: [key: string]; reload: []; sync: []; check: [] }>()
</script>

<template>
  <section class="panel dock-panel">
    <div class="panel-head">
      <b>网站比赛</b>
      <button type="button" class="btn btn-ghost btn-sm" :disabled="listBusy" title="重新读取网站上的比赛" @click="emit('reload')">
        <AppIcon name="refresh" />{{ listBusy ? '读取中' : '读取' }}
      </button>
    </div>
    <select
      class="select"
      aria-label="选择网站比赛"
      :value="selected"
      @change="emit('choose', ($event.target as HTMLSelectElement).value)"
    >
      <option value="">未选择</option>
      <option v-for="source in matches" :key="source.key" :value="source.key">{{ source.label }}</option>
    </select>
    <div class="dock-actions">
      <button type="button" class="btn btn-primary" :disabled="syncBusy || !selected" @click="emit('sync')">
        {{ syncBusy ? '同步中…' : '同步比赛资料' }}
      </button>
      <button type="button" class="btn" :disabled="checkBusy || !canCheck" title="让网站确认能收到这台电脑的数据" @click="emit('check')">
        <AppIcon name="check" />{{ checkBusy ? '检查中' : '检查连接' }}
      </button>
    </div>
    <div class="kv"><span>最近网站确认</span><b class="num" :class="{ good: confirmedFresh }">{{ lastConfirmed }}</b></div>
  </section>
</template>

<style scoped>
.dock-panel { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.dock-actions { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
</style>
