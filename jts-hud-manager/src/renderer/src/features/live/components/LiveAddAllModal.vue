<script setup lang="ts">
// 把这一边的全部选手加入同一支战队（已录入的选手会改成这支战队）
import { computed, ref } from 'vue'
import AppIcon from '../../../components/ui/AppIcon.vue'
import TeamBadge from '../../../components/ui/TeamBadge.vue'
import { assetUrl, teamAbbr } from '../../../utils/display'

const props = defineProps<{
  isOpen: boolean
  side: 'CT' | 'T' | null
  teams: any[]
  playerCount: number
  selectedTeamId: string
  isAdding: boolean
}>()
const emit = defineEmits<{ 'update:selectedTeamId': [value: string]; close: []; confirm: [] }>()

const searchQuery = ref('')
const filteredTeams = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return query ? props.teams.filter((team) => String(team.name || '').toLowerCase().includes(query)) : props.teams
})
</script>

<template>
  <div v-if="isOpen" class="dialog-backdrop" @mousedown.self="emit('close')">
    <div class="dialog" role="dialog" :aria-label="`把全部 ${side} 选手加入战队`">
      <div class="dialog-head">
        <h2>把全部 {{ side }} 选手加入战队</h2>
        <button type="button" class="icon-btn dialog-close" title="关闭" @click="emit('close')"><AppIcon name="x" /></button>
      </div>
      <div class="dialog-body add-body">
        <p class="hint">选一支战队，当前 <b class="num">{{ playerCount }}</b> 名选手会全部加入。已录入的选手会改到这支战队。</p>
        <input v-model="searchQuery" class="input" type="search" placeholder="搜索战队" />
        <div v-if="teams.length === 0" class="empty-state">还没有战队，请先到「战队」页创建。</div>
        <div v-else-if="filteredTeams.length === 0" class="empty-state">没有找到符合条件的战队。</div>
        <div v-else class="team-list">
          <button
            v-for="team in filteredTeams"
            :key="team._id"
            type="button"
            class="team-option"
            :class="{ picked: selectedTeamId === team._id }"
            @click="emit('update:selectedTeamId', team._id)"
          >
            <TeamBadge :logo="assetUrl(team.logo)" :abbr="teamAbbr(team.name, team.shortName)" size="sm" />
            <span class="team-option-name">{{ team.name }}</span>
            <AppIcon v-if="selectedTeamId === team._id" name="check" class="picked-icon" />
          </button>
        </div>
      </div>
      <div class="dialog-foot">
        <button type="button" class="btn" @click="emit('close')">取消</button>
        <button type="button" class="btn btn-primary" :disabled="!selectedTeamId || isAdding" @click="emit('confirm')">
          {{ isAdding ? '正在添加…' : '添加全部选手' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.add-body { display: flex; flex-direction: column; gap: 12px; }
.add-body .hint b { color: var(--text); }
.team-list { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.team-option { display: flex; align-items: center; gap: 10px; height: 44px; padding: 0 12px; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--bg-raised); color: var(--text-2); text-align: left; }
.team-option:hover { border-color: var(--border-strong); background: var(--bg-hover); }
.team-option.picked { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
.team-option-name { flex: 1; font-weight: 600; }
.picked-icon { color: var(--accent); }
</style>
