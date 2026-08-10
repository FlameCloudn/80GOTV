<script setup lang="ts">
const props = defineProps<{
  modelValue?: boolean;
  label?: string;
  disabled?: boolean;
  size?: 'lg' | 'md' | 'sm';
}>();

defineEmits<{
  'update:modelValue': [value: boolean];
}>();
</script>

<template>
  <div class="flex items-center justify-between" :class="{ 'opacity-50 cursor-not-allowed': disabled }">
    <!-- Label -->
    <label v-if="label" class="text-sm text-zinc-300 cursor-pointer select-none mr-2">
      {{ label }}
    </label>

    <!-- Toggle Switch -->
    <button
      type="button"
      :disabled="disabled"
      @click="$emit('update:modelValue', !modelValue)"
      :class="[
        'relative rounded-full transition-colors shrink-0 hover:cursor-pointer',
        // Size
        size === 'lg' && 'w-12 h-7',
        size === 'md' && 'w-11 h-6',
        size === 'sm' && 'w-9 h-5',
        // State
        modelValue ? 'bg-primary' : 'bg-zinc-700',
        disabled && 'cursor-not-allowed',
      ]"
    >
      <span
        :class="[
          'absolute top-0.5 left-0.5 rounded-full bg-white shadow transition-transform',
          size === 'lg' && 'w-6 h-6',
          size === 'md' && 'w-5 h-5',
          size === 'sm' && 'w-4 h-4',
          modelValue && (size === 'lg' ? 'translate-x-5' : size === 'sm' ? 'translate-x-4' : 'translate-x-5'),
        ]"
      />
    </button>
  </div>
</template>
