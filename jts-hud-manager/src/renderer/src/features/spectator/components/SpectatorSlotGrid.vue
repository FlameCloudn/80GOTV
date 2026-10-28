<script setup lang="ts">
// 数字键 1–0：每个键上写着分给谁（CT 蓝框、T 橙框），下面的下拉框换人
import { computed } from 'vue'
import type { SelectOption } from '../../../components/base/BaseSelect.vue'
import BaseSelect from '../../../components/base/BaseSelect.vue'
import AppIcon from '../../../components/ui/AppIcon.vue'
import type { LivePlayer } from '../composables/useSpectator'

const props = defineProps<{
  slots: Record<number, string>
  livePlayers: LivePlayer[]
  allPlayerNames: string[]
  sideForName: (name: string) => 'CT' | 'T' | null
  slotKeys: Record<number, string>
  warnedNames: string[]
}>()
defineEmits<{ (e: 'clear-slot', slot: number): void; (e: 'fill-from-cs2'): void }>()

// 下拉选项：比赛里的选手；已经存下但不在比赛里的人也保留，免得被冲掉
const optionsFor = (slot: number): SelectOption[] => {
  const options: SelectOption[] = props.livePlayers.map((player) => ({ value: player.name, label: player.name }))
  const saved = props.slots[slot]
  if (saved && !props.allPlayerNames.includes(saved)) options.push({ value: saved, label: saved })
  return options
}
const slotOptions = computed(() => Object.fromEntries(Array.from({ length: 10 }, (_, i) => [i + 1, optionsFor(i + 1)])))
const sideClass = (slot: number) => {
  const name = props.slots[slot]
  if (!name) return ''
  return (props.sideForName(name) || 'none').toLowerCase()
}
</script>

<template>
  <section class="panel panel-pad">
    <div class="panel-head">
      <b>数字键对应选手</b>
      <button v-if="livePlayers.length > 0" type="button" class="btn btn-sm" title="按 CS2 现在的观战位置自动填写" @click="$emit('fill-from-cs2')">
        <AppIcon name="refresh" />从 CS2 自动填写
      </button>
    </div>
    <div class="keys">
      <div v-for="slot in 10" :key="slot" class="key-col">
        <div class="keycap" :class="sideClass(slot)">
          <AppIcon v-if="slots[slot] && warnedNames.includes(slots[slot])" name="alert" class="key-warn" title="名字以数字开头，CS2 绑不了这个人" />
          <button v-if="slots[slot]" type="button" class="key-clear" title="清空这个按键" @click="$emit('clear-slot', slot)"><AppIcon name="x" /></button>
          <span class="key-char num">{{ slotKeys[slot] }}</span>
          <span v-if="slots[slot]" class="key-name" :title="slots[slot]">{{ slots[slot] }}</span>
          <span v-else class="key-name empty">空</span>
        </div>
        <BaseSelect v-model="slots[slot]" :options="slotOptions[slot]" size="sm" placeholder="未分配" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.keys { margin-top: 12px; display: grid; grid-template-columns: repeat(10, minmax(0, 1fr)); gap: 8px; }
.key-col { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.keycap { position: relative; height: 84px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; padding: 0 6px; border-radius: var(--radius-lg); background: var(--bg-raised); border: 2px solid var(--border-strong); box-shadow: 0 3px 0 rgba(0, 0, 0, 0.5); }
.keycap.ct { border-color: var(--ct); background: linear-gradient(180deg, var(--ct-soft), transparent), var(--bg-raised); }
.keycap.t { border-color: var(--t); background: linear-gradient(180deg, var(--t-soft), transparent), var(--bg-raised); }
.keycap.none { border-color: var(--text-3); }
.key-char { font-size: 28px; font-weight: 800; line-height: 1; }
.key-name { max-width: 100%; font-size: 12px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ct .key-name { color: var(--ct); }
.t .key-name { color: var(--t); }
.key-name.empty { color: var(--text-3); font-weight: 500; }
.key-clear { position: absolute; top: 4px; right: 4px; width: 20px; height: 20px; display: grid; place-items: center; border: none; border-radius: var(--radius-sm); background: transparent; color: var(--text-3); }
.key-clear:hover { color: var(--live); background: var(--bg-hover); }
.key-clear .icon { width: 12px; height: 12px; }
.key-warn { position: absolute; top: 6px; left: 6px; width: 14px; height: 14px; color: var(--gold); }
</style>
