<script setup lang="ts">
// 输入框：标签 + 输入 + 出错时红框（错误文字同时在右上角提示）/ 提示文字
withDefaults(
  defineProps<{
    modelValue?: string | number
    label?: string
    placeholder?: string
    type?: 'text' | 'number' | 'email' | 'password' | 'search' | 'url'
    disabled?: boolean
    error?: string
    // 只把输入框标红（错误内容在右上角提示里说），不在下面写字
    invalid?: boolean
    hint?: string
    size?: 'lg' | 'md' | 'sm'
  }>(),
  { type: 'text', disabled: false, size: 'md' }
)
defineEmits<{ 'update:modelValue': [value: string | number] }>()
</script>

<template>
  <div class="field">
    <label v-if="label">{{ label }}</label>
    <input
      class="input"
      :class="[{ 'has-error': error || invalid }, size === 'sm' && 'input-sm', size === 'lg' && 'input-lg']"
      :value="modelValue"
      :type="type"
      :disabled="disabled"
      :placeholder="placeholder"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <p v-if="error" class="field-error">{{ error }}</p>
    <p v-else-if="hint" class="hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.input-sm { height: 28px; font-size: 12px; }
.input-lg { height: 40px; font-size: 14px; }
.input:disabled { opacity: 0.5; cursor: not-allowed; }
.field-error { font-size: 12px; color: #ff9d95; }
</style>
