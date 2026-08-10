<script setup lang="ts">
const props = withDefaults(defineProps<{
  modelValue?: string | number;
  label?: string;
  placeholder?: string;
  type?: 'text' | 'number' | 'email' | 'password' | 'search' | 'url';
  disabled?: boolean;
  error?: string;
  hint?: string;
  size?: 'lg' | 'md' | 'sm';
}>(), {
  type: 'text',
  disabled: false,
  size: 'md',
});

defineEmits<{
  'update:modelValue': [value: string | number];
}>();
</script>

<template>
  <div class="w-full">
    <!-- Label -->
    <label v-if="label" class="block text-xs font-semibold text-zinc-400 mb-1.5">
      {{ label }}
    </label>

    <!-- Input -->
    <input
      :value="modelValue"
      :type="type"
      :disabled="disabled"
      :placeholder="placeholder"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      :class="[
        'w-full bg-surface border rounded-lg text-text-main focus:outline-none transition-colors',
        'placeholder:text-zinc-600',
        // Size
        size === 'lg' && 'px-4 py-3 text-base',
        size === 'md' && 'px-3 py-2 text-sm',
        size === 'sm' && 'px-2.5 py-1.5 text-xs',
        // Border color
        error ? 'border-red-900/50 focus:border-red-600' : 'border-zinc-700 focus:border-primary',
        // Disabled
        disabled && 'opacity-50 cursor-not-allowed',
      ]"
    />

    <!-- Error message -->
    <p v-if="error" class="mt-1.5 text-xs text-red-400">{{ error }}</p>

    <!-- Hint text -->
    <p v-else-if="hint" class="mt-1.5 text-xs text-zinc-500">{{ hint }}</p>
  </div>
</template>
