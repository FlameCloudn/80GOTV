<script setup lang="ts">
// 创建 / 编辑比赛：赛制、是否当前比赛、左右两队和初始大比分、地图选择顺序（最多 9 项）
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { SelectOption } from '../components/base/BaseSelect.vue'
import BaseSelect from '../components/base/BaseSelect.vue'
import BaseInput from '../components/base/BaseInput.vue'
import AppIcon from '../components/ui/AppIcon.vue'
import TeamBadge from '../components/ui/TeamBadge.vue'
import VetoDialog, { type VetoForm } from '../features/matches/components/VetoDialog.vue'
import { useMatches } from '../features/matches/composables/useMatches'
import { useTeams } from '../features/teams/composables/useTeams'
import { errorText, showToast } from '../composables/useToasts'
import { API_URL } from '../index'
import { assetUrl, mapLabel, teamAbbr } from '../utils/display'

const router = useRouter()
const route = useRoute()
const { saveMatch } = useMatches()
const { teams, fetchTeams } = useTeams()

const SLOT_COUNT = 9
const MATCH_TYPES = ['bo1', 'bo2', 'bo3', 'bo5']
const TYPE_LABEL: Record<string, { text: string; tone: string }> = {
  ban: { text: '禁用', tone: 'tag-bad' },
  pick: { text: '选择', tone: 'tag-ok' },
  decider: { text: '决胜', tone: 'tag-warn' }
}

const isEditing = computed(() => Boolean(route.params.id))
const isSaving = ref(false)

const emptyForm = () => ({
  current: false,
  matchType: 'bo3',
  left: { id: '' as string, wins: 0 },
  right: { id: '' as string, wins: 0 },
  vetos: Array.from({ length: SLOT_COUNT }, () => null) as (any | null)[]
})
const form = ref(emptyForm())

const teamOptions = (excludeId: string): SelectOption[] =>
  teams.value.filter((team) => team._id !== excludeId).map((team) => ({ value: team._id, label: team.name }))
const leftOptions = computed(() => teamOptions(form.value.right.id))
const rightOptions = computed(() => teamOptions(form.value.left.id))

const teamOf = (id: string | null) => (id ? teams.value.find((team) => team._id === id) : undefined)
const teamName = (id: string | null) => (id ? teamOf(id)?.name ?? '未知' : '待定')
const badgeOf = (id: string) => {
  const team = teamOf(id)
  return { logo: assetUrl(team?.logo), abbr: team ? teamAbbr(team.name, team.shortName) : '?' }
}

const bothTeamsSelected = computed(
  () => Boolean(form.value.left.id && form.value.right.id) && form.value.left.id !== form.value.right.id
)
const filledCount = computed(() => form.value.vetos.filter(Boolean).length)

const loadMatch = async () => {
  try {
    const response = await fetch(`${API_URL}/match/${route.params.id}`)
    if (!response.ok) throw new Error('读取比赛失败')
    const data = await response.json()
    const padded = Array.from({ length: SLOT_COUNT }, (_, index) => data.vetos?.[index] ?? null)
    form.value = { ...data, vetos: padded }
  } catch (error) {
    showToast(errorText(error), 'error', { key: 'match-form' })
  }
}

onMounted(async () => {
  await fetchTeams()
  if (isEditing.value) await loadMatch()
})

// --- 地图选择顺序的一项 ---
const editingSlot = ref<number | null>(null)
const vetoForm = ref<VetoForm>(defaultVeto())

function defaultVeto(): VetoForm {
  return { teamId: '', mapName: 'de_mirage', side: 'NO', type: 'pick', reverseSide: false, openingCtTeamId: undefined, sideSource: 'unknown', mapEnd: false, winner: '', score: {} }
}

const openSlot = (index: number) => {
  if (!bothTeamsSelected.value) return
  const existing = form.value.vetos[index]
  vetoForm.value = existing
    ? { ...defaultVeto(), ...existing, score: { ...(existing.score ?? {}) } }
    : { ...defaultVeto(), teamId: form.value.left.id ?? '' }
  editingSlot.value = index
}
const saveSlot = () => {
  if (editingSlot.value === null) return
  form.value.vetos[editingSlot.value] = { ...vetoForm.value }
  editingSlot.value = null
}
const clearSlot = (index: number) => (form.value.vetos[index] = null)
const slotScore = (veto: any) => {
  const left = veto?.score?.[form.value.left.id]
  const right = veto?.score?.[form.value.right.id]
  return left != null && right != null && (Number(left) > 0 || Number(right) > 0) ? `${left}:${right}` : ''
}

const handleSave = async () => {
  isSaving.value = true
  try {
    const payload = { ...form.value, vetos: form.value.vetos.filter(Boolean) }
    await saveMatch(payload, isEditing.value ? String(route.params.id) : null)
    void router.push('/matches')
  } catch (error) {
    showToast(errorText(error), 'error', { key: 'match-form' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <button type="button" class="icon-btn" title="返回比赛列表" @click="router.push('/matches')"><AppIcon name="chevronLeft" /></button>
      <div class="page-title"><div class="kicker">Match</div><h1>{{ isEditing ? '编辑比赛' : '创建比赛' }}</h1></div>
      <div class="page-actions">
        <button type="button" class="btn" @click="router.push('/matches')">取消</button>
        <button type="button" class="btn btn-primary" :disabled="isSaving" @click="handleSave">
          {{ isSaving ? '正在保存…' : isEditing ? '保存更改' : '创建比赛' }}
        </button>
      </div>
    </div>

    <div class="form-wrap">
      <section class="panel panel-pad format-row">
        <div class="field">
          <span class="field-label">比赛赛制</span>
          <div class="seg">
            <button v-for="type in MATCH_TYPES" :key="type" type="button" :class="{ active: form.matchType === type }" @click="form.matchType = type">
              {{ type.toUpperCase() }}
            </button>
          </div>
        </div>
        <div class="current-toggle">
          <span>设为当前比赛</span>
          <button type="button" class="switch" :class="{ on: form.current }" role="switch" :aria-checked="form.current" @click="form.current = !form.current" />
        </div>
      </section>

      <section class="teams-row">
        <div v-for="side in (['left', 'right'] as const)" :key="side" class="panel panel-pad team-panel">
          <div class="team-head">
            <TeamBadge v-bind="badgeOf(form[side].id)" />
            <div>
              <div class="kicker">{{ side === 'left' ? '左侧战队' : '右侧战队' }}</div>
              <b>{{ teamName(form[side].id) }}</b>
            </div>
          </div>
          <BaseSelect v-model="form[side].id" placeholder="搜索战队…" :options="side === 'left' ? leftOptions : rightOptions" clearable searchable />
          <BaseInput v-model.number="form[side].wins" type="number" label="初始大比分" />
        </div>
        <span class="vs">VS</span>
      </section>

      <section class="panel panel-pad">
        <div class="panel-head">
          <div>
            <h2>地图选择顺序</h2>
            <p class="hint">{{ bothTeamsSelected ? `已设置 ${filledCount} / ${SLOT_COUNT} 项，点任意一项编辑。` : '选好两支战队后才能设置地图。' }}</p>
          </div>
        </div>
        <div v-if="!bothTeamsSelected" class="empty-state slots-locked">
          <AppIcon name="lock" />
          <span>请先在上面选择两支战队</span>
        </div>
        <div v-else class="slots">
          <div v-for="(veto, index) in form.vetos" :key="index" class="slot" :class="{ empty: !veto }">
            <span class="slot-no num">{{ String(index + 1).padStart(2, '0') }}</span>
            <template v-if="!veto">
              <span class="slot-empty">空</span>
              <button type="button" class="btn btn-sm" @click="openSlot(index)"><AppIcon name="plus" />设置</button>
            </template>
            <template v-else>
              <span class="tag" :class="TYPE_LABEL[veto.type]?.tone">{{ TYPE_LABEL[veto.type]?.text || veto.type }}</span>
              <b class="slot-map" @click="openSlot(index)">{{ mapLabel(veto.mapName) }}</b>
              <span class="slot-team">{{ veto.type === 'decider' ? '决胜地图' : teamName(veto.teamId) }}</span>
              <span v-if="veto.side !== 'NO'" class="tag" :class="veto.side === 'CT' ? 'tag-ct' : 'tag-t'">{{ veto.side }}</span>
              <span v-if="slotScore(veto)" class="slot-score num">{{ slotScore(veto) }}</span>
              <span v-if="veto.mapEnd" class="tag tag-ok">已结束</span>
              <span class="slot-actions">
                <button type="button" class="icon-btn" title="编辑这一项" @click="openSlot(index)"><AppIcon name="edit" /></button>
                <button type="button" class="icon-btn danger" title="清空这一项" @click="clearSlot(index)"><AppIcon name="x" /></button>
              </span>
            </template>
          </div>
        </div>
      </section>
    </div>

    <VetoDialog
      v-if="editingSlot !== null"
      v-model="vetoForm"
      :slot-number="editingSlot + 1"
      :left-id="form.left.id"
      :right-id="form.right.id"
      :left-name="teamName(form.left.id)"
      :right-name="teamName(form.right.id)"
      @close="editingSlot = null"
      @save="saveSlot"
    />
  </div>
</template>

<style scoped>
.form-wrap { width: 100%; max-width: 920px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.format-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.current-toggle { display: flex; align-items: center; gap: 10px; height: 34px; font-size: 13px; color: var(--text-2); }
.teams-row { position: relative; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.team-panel { display: flex; flex-direction: column; gap: 12px; }
.team-head { display: flex; align-items: center; gap: 12px; }
.team-head b { font-size: 15px; }
.vs { position: absolute; left: 50%; top: 32px; transform: translateX(-50%); width: 36px; height: 36px; display: grid; place-items: center; border-radius: 50%; background: var(--bg); border: 1px solid var(--border-strong); font: 800 11px/1 'Montserrat', sans-serif; color: var(--text-3); }
.slots-locked { margin-top: 12px; }
.slots { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.slot { height: 44px; display: flex; align-items: center; gap: 10px; padding: 0 8px 0 12px; border-radius: var(--radius-md); background: var(--bg-raised); border: 1px solid var(--border); }
.slot.empty { background: transparent; border-style: dashed; }
.slot-no { width: 22px; font-size: 12px; font-weight: 700; color: var(--text-3); }
.slot-empty { flex: 1; font-size: 12px; color: var(--text-3); }
.slot-map { min-width: 90px; font: 700 14px/1 'Montserrat', sans-serif; cursor: pointer; }
.slot-team { flex: 1; min-width: 0; font-size: 13px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.slot-score { font-size: 13px; font-weight: 700; }
.slot-actions { display: inline-flex; gap: 6px; margin-left: 4px; }
</style>
