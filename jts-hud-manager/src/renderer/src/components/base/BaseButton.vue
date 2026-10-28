<script setup lang="ts">
// 按钮：样式统一用 main.css 的 .btn；variant / size 和旧版一样
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
    size?: 'lg' | 'md' | 'sm' | 'xs'
    disabled?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  { variant: 'secondary', size: 'md', disabled: false, type: 'button' }
)
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    class="btn"
    :class="[
      variant === 'primary' && 'btn-primary',
      variant === 'danger' && 'btn-danger',
      variant === 'ghost' && 'btn-ghost',
      size === 'lg' && 'btn-lg',
      (size === 'sm' || size === 'xs') && 'btn-sm',
      size === 'xs' && 'btn-xs'
    ]"
  >
    <slot />
  </button>
</template>

<style scoped>
.btn-xs { height: 24px; padding: 0 7px; }
</style>
