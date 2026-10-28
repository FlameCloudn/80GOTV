<script setup lang="ts">
// 下拉框：普通下拉，或可搜索的下拉（searchable）；可清空（clearable）
import { computed, ref } from 'vue'
import AppIcon from '../ui/AppIcon.vue'

export interface SelectOption {
  value: string | number
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    label?: string
    placeholder?: string
    options: SelectOption[]
    disabled?: boolean
    error?: string
    hint?: string
    size?: 'lg' | 'md' | 'sm'
    clearable?: boolean
    searchable?: boolean
  }>(),
  { size: 'md', disabled: false, clearable: false, searchable: false }
)
const emit = defineEmits<{ 'update:modelValue': [value: string | number | null] }>()

const isOpen = ref(false)
const searchQuery = ref('')

const selectedLabel = computed(() => props.options.find((opt) => opt.value === props.modelValue)?.label ?? '')
const inputDisplayValue = computed(() => (isOpen.value ? searchQuery.value : selectedLabel.value))
const filteredOptions = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!props.searchable || !query) return props.options
  return props.options.filter((opt) => opt.label.toLowerCase().includes(query))
})

const handleSelect = (value: string | number) => {
  emit('update:modelValue', value)
  isOpen.value = false
  searchQuery.value = ''
}
const handleClear = () => {
  emit('update:modelValue', null)
  searchQuery.value = ''
}
</script>

<template>
  <div class="field">
    <label v-if="label">{{ label }}</label>

    <div v-if="!searchable" class="select-wrap">
      <select
        class="select"
        :class="[{ 'has-error': error }, size === 'sm' && 'select-sm']"
        :value="modelValue"
        :disabled="disabled"
        @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-if="placeholder || !modelValue" value="">{{ placeholder || '请选择' }}</option>
        <option v-for="opt in options" :key="opt.value" :value="opt.value" :disabled="opt.disabled">{{ opt.label }}</option>
      </select>
      <button v-if="clearable && modelValue" type="button" class="clear-btn" title="清空" @click="handleClear">
        <AppIcon name="x" />
      </button>
    </div>

    <div v-else class="select-wrap">
      <input
        type="text"
        class="input search-input"
        :class="[{ 'has-error': error }, size === 'sm' && 'select-sm']"
        :placeholder="placeholder || '搜索…'"
        :value="inputDisplayValue"
        :disabled="disabled"
        @input="searchQuery = ($event.target as HTMLInputElement).value"
        @focus="isOpen = true"
      />
      <AppIcon name="chevronDown" class="chevron" />
      <button v-if="clearable && modelValue" type="button" class="clear-btn" title="清空" @click="handleClear">
        <AppIcon name="x" />
      </button>
      <div v-if="isOpen" class="menu">
        <div v-if="filteredOptions.length === 0" class="menu-empty">没有找到结果</div>
        <button
          v-for="opt in filteredOptions"
          :key="opt.value"
          type="button"
          class="menu-item"
          :class="{ selected: modelValue === opt.value }"
          :disabled="opt.disabled"
          @click="handleSelect(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>
      <div v-if="isOpen" class="menu-mask" @click="isOpen = false" />
    </div>

    <p v-if="error" class="field-error">{{ error }}</p>
    <p v-else-if="hint" class="hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.select-wrap { position: relative; }
.select:disabled, .search-input:disabled { opacity: 0.5; cursor: not-allowed; }
.select-sm { height: 28px; font-size: 12px; }
.search-input { padding-right: 52px; }
.chevron { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); width: 14px; height: 14px; color: var(--text-3); pointer-events: none; }
.clear-btn { position: absolute; right: 28px; top: 50%; transform: translateY(-50%); width: 20px; height: 20px; display: grid; place-items: center; border: none; border-radius: var(--radius-sm); background: transparent; color: var(--text-3); }
.clear-btn:hover { color: var(--text); background: var(--bg-hover); }
.clear-btn .icon { width: 12px; height: 12px; }
.menu { position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 60; max-height: 256px; overflow-y: auto; padding: 4px; border-radius: var(--radius-md); background: var(--bg-raised); border: 1px solid var(--border-strong); box-shadow: 0 12px 28px rgba(0, 0, 0, 0.45); }
.menu-empty { padding: 8px; text-align: center; font-size: 12px; color: var(--text-3); }
.menu-item { width: 100%; display: block; padding: 7px 10px; border: none; border-radius: var(--radius-sm); background: transparent; color: var(--text-2); text-align: left; font-size: 13px; }
.menu-item:hover:not(:disabled) { background: var(--bg-hover); color: var(--text); }
.menu-item.selected { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.menu-item:disabled { opacity: 0.45; cursor: not-allowed; }
.menu-mask { position: fixed; inset: 0; z-index: 55; }
.field-error { font-size: 12px; color: #ff9d95; }
</style>
