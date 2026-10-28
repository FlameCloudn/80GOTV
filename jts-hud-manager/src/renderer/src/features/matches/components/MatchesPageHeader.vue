<script setup lang="ts">
// 比赛页标题行：筛选（全部 / 网站同步 / 手动创建）+ 搜索 + 创建比赛
import AppIcon from '../../../components/ui/AppIcon.vue'
import PageHeader from '../../../components/ui/PageHeader.vue'
import type { MatchFilter } from '../composables/useMatchesView'

defineProps<{ filter: MatchFilter; search: string; counts: Record<MatchFilter, number> }>()
const emit = defineEmits<{ create: []; 'update:filter': [value: MatchFilter]; 'update:search': [value: string] }>()

const FILTERS: { key: MatchFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'website', label: '网站同步' },
  { key: 'manual', label: '手动创建' }
]
</script>

<template>
  <PageHeader kicker="Matches" title="比赛">
    <div class="seg">
      <button v-for="item in FILTERS" :key="item.key" type="button" :class="{ active: filter === item.key }" @click="emit('update:filter', item.key)">
        {{ item.label }}<span class="count">{{ counts[item.key] }}</span>
      </button>
    </div>
    <div class="search">
      <AppIcon name="search" class="search-icon" />
      <input class="input" :value="search" placeholder="搜索战队" @input="emit('update:search', ($event.target as HTMLInputElement).value)" />
    </div>
    <button type="button" class="btn btn-primary" @click="emit('create')"><AppIcon name="plus" />创建比赛</button>
  </PageHeader>
</template>

<style scoped>
.search { position: relative; }
.search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-3); pointer-events: none; }
.search .input { width: 200px; padding-left: 32px; }
</style>
