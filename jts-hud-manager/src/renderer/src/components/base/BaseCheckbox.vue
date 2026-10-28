<script setup lang="ts">
// 开关：左边文字，右边开关
defineProps<{
  modelValue?: boolean
  label?: string
  disabled?: boolean
  size?: 'lg' | 'md' | 'sm'
}>()
defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <div class="toggle-row" :class="{ disabled }">
    <label v-if="label" class="toggle-label" @click="!disabled && $emit('update:modelValue', !modelValue)">{{ label }}</label>
    <button
      type="button"
      class="switch"
      :class="{ on: modelValue }"
      role="switch"
      :aria-checked="Boolean(modelValue)"
      :disabled="disabled"
      @click="$emit('update:modelValue', !modelValue)"
    />
  </div>
</template>

<style scoped>
.toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.toggle-row.disabled { opacity: 0.5; }
.toggle-label { font-size: 13px; color: var(--text-2); cursor: pointer; user-select: none; }
</style>
