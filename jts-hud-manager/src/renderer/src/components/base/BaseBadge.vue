<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'amber' | 'zinc' | 'blue' | 'orange' | 'emerald' | 'red';
}>(), {
  variant: 'zinc',
});
</script>

<template>
  <span
    :class="[
      'text-xs px-1.5 py-0.5 rounded uppercase font-bold border',
      variant === 'amber'   && 'bg-amber-500/20 border-amber-500/40 text-amber-400',
      variant === 'zinc'    && 'bg-zinc-700 border-zinc-600 text-zinc-400',
      variant === 'blue'    && 'bg-blue-900/30 border-blue-500/40 text-blue-400',
      variant === 'orange'  && 'bg-orange-900/30 border-orange-500/40 text-orange-400',
      variant === 'emerald' && 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400',
      variant === 'red'     && 'bg-red-600/20 border-red-600/40 text-red-400',
    ]"
  >
    <slot />
  </span>
</template>
