<script setup lang="ts">
// 设置地图选择顺序里的一项：地图、哪支队、禁用/选择/决胜、起始阵营；可选手动填结果
import { computed, ref, watch } from 'vue'
import AppIcon from '../../../components/ui/AppIcon.vue'
import BaseSelect, { type SelectOption } from '../../../components/base/BaseSelect.vue'
import BaseInput from '../../../components/base/BaseInput.vue'
import BaseCheckbox from '../../../components/base/BaseCheckbox.vue'
import { mapLabel } from '../../../utils/display'

export type VetoForm = {
  teamId: string
  mapName: string
  side: string
  type: string
  reverseSide: boolean
  openingCtTeamId?: string
  sideSource: 'website_bp' | 'tgpro_stable_gsi' | 'legacy_manual' | 'unknown'
  mapEnd: boolean
  winner: string
  score: Record<string, number>
}

const CS2_MAPS = [
  'de_ancient', 'de_anubis', 'de_dust2', 'de_inferno',
  'de_mirage', 'de_nuke', 'de_overpass', 'de_train', 'de_vertigo', 'de_cache'
]
const SIDES = ['CT', 'T', 'NO'] as const
const TYPE_OPTIONS: SelectOption[] = [
  { value: 'ban', label: '禁用地图' },
  { value: 'pick', label: '选择地图' },
  { value: 'decider', label: '决胜地图' }
]

const props = defineProps<{ slotNumber: number; leftId: string; rightId: string; leftName: string; rightName: string }>()
const form = defineModel<VetoForm>({ required: true })
const emit = defineEmits<{ close: []; save: [] }>()

const showResult = ref(false)
const mapOptions: SelectOption[] = CS2_MAPS.map((map) => ({ value: map, label: mapLabel(map) }))
const teamOptions = computed<SelectOption[]>(() => [
  { value: props.leftId, label: props.leftName },
  { value: props.rightId, label: props.rightName }
])
const winnerOptions = computed<SelectOption[]>(() => [{ value: '', label: '无' }, ...teamOptions.value])
// 阵营由网站 BP 或游戏数据确定时，不能再手动交换
const sideLocked = computed(() =>
  Boolean(form.value.openingCtTeamId) || form.value.sideSource === 'website_bp' || form.value.sideSource === 'tgpro_stable_gsi'
)

// 选“决胜地图”时不属于任何一队
watch(() => form.value.type, (type) => {
  if (type === 'decider') form.value.teamId = ''
})

const scoreOf = (teamId: string) => form.value.score?.[teamId] ?? 0
const setScore = (teamId: string, value: string | number) => {
  form.value.score = { ...(form.value.score || {}), [teamId]: Number(value) }
}
</script>

<template>
  <div class="dialog-backdrop" @mousedown.self="emit('close')">
    <div class="dialog" role="dialog" :aria-label="`设置第 ${slotNumber} 项`">
      <div class="dialog-head">
        <h2>设置第 {{ slotNumber }} 项</h2>
        <button type="button" class="icon-btn dialog-close" title="关闭" @click="emit('close')"><AppIcon name="x" /></button>
      </div>
      <div class="dialog-body veto-body">
        <BaseSelect v-model="form.mapName" label="地图" :options="mapOptions" />
        <div class="two-col">
          <BaseSelect v-model="form.teamId" label="战队" :options="teamOptions" :disabled="form.type === 'decider'" />
          <BaseSelect v-model="form.type" label="选择类型" :options="TYPE_OPTIONS" />
        </div>
        <div class="field">
          <span class="field-label">起始阵营</span>
          <div class="side-pick">
            <button
              v-for="side in SIDES"
              :key="side"
              type="button"
              class="side-btn"
              :class="[side.toLowerCase(), { active: form.side === side }]"
              @click="form.side = side"
            >
              {{ side === 'NO' ? '不指定' : side }}
            </button>
          </div>
        </div>

        <button type="button" class="result-toggle" @click="showResult = !showResult">
          <span>手动填写结果（可选）</span>
          <AppIcon name="chevronDown" :class="{ open: showResult }" />
        </button>
        <template v-if="showResult">
          <BaseSelect v-model="form.winner" label="获胜战队" :options="winnerOptions" />
          <div class="two-col">
            <BaseInput type="number" :model-value="scoreOf(leftId)" :label="`${leftName} 得分`" placeholder="0" @update:model-value="setScore(leftId, $event)" />
            <BaseInput type="number" :model-value="scoreOf(rightId)" :label="`${rightName} 得分`" placeholder="0" @update:model-value="setScore(rightId, $event)" />
          </div>
          <BaseCheckbox v-model="form.reverseSide" label="交换阵营" :disabled="sideLocked" />
          <BaseCheckbox v-model="form.mapEnd" label="地图已结束" />
        </template>
      </div>
      <div class="dialog-foot">
        <button type="button" class="btn" @click="emit('close')">取消</button>
        <button type="button" class="btn btn-primary" @click="emit('save')">保存这一项</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.veto-body { display: flex; flex-direction: column; gap: 14px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.side-pick { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.side-btn { height: 34px; border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--bg-input); color: var(--text-2); font-weight: 700; font-size: 12px; }
.side-btn:hover { background: var(--bg-hover); }
.side-btn.ct.active { background: var(--ct-soft); border-color: var(--ct); color: var(--ct); }
.side-btn.t.active { background: var(--t-soft); border-color: var(--t); color: var(--t); }
.side-btn.no.active { background: var(--bg-hover); border-color: var(--text-3); color: var(--text); }
.result-toggle { display: flex; align-items: center; justify-content: center; gap: 6px; height: 30px; border: 1px dashed var(--border-strong); border-radius: var(--radius-md); background: transparent; color: var(--gold); font-size: 12px; font-weight: 600; }
.result-toggle .icon { width: 13px; height: 13px; transition: transform 0.15s; }
.result-toggle .icon.open { transform: rotate(180deg); }
</style>
