<script setup lang="ts">
const props = withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'lg' | 'md' | 'sm' | 'xs';
  disabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
}>(), {
  variant: 'secondary',
  size: 'md',
  disabled: false,
  type: 'button',
});
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    :class="[
      'rounded-lg font-medium transition-colors flex items-center gap-2',
      // Variant
      variant === 'primary'   && 'hover:cursor-pointer bg-primary/70 text-text-main hover:bg-primary/50 shadow shadow-primary/20 font-semibold',
      variant === 'secondary' && 'hover:cursor-pointer bg-zinc-800 border border-zinc-700 text-zinc-300 hover:text-text-main hover:bg-zinc-700',
      variant === 'danger'    && 'hover:cursor-pointer bg-zinc-800 border border-red-900/50 text-red-400 hover:bg-red-900/30 hover:text-red-300',
      variant === 'ghost'     && 'hover:cursor-pointer text-zinc-500 hover:text-zinc-200',
      // Size
      size === 'lg' && 'px-6 py-3 text-base',
      size === 'md' && 'px-4 py-2 text-sm',
      size === 'sm' && 'px-3 py-1.5 text-xs font-bold',
      size === 'xs' && 'px-2 py-0.5 text-xs font-bold rounded',
      // Disabled
      disabled && 'disabled:opacity-40 disabled:cursor-not-allowed',
    ]"
  >
    <slot />
  </button>
</template>
