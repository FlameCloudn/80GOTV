<script setup lang="ts">
import { ref, computed } from 'vue';

export interface SelectOption {
  value: string | number;
  label: string;
  disabled?: boolean;
}

const props = withDefaults(defineProps<{
  modelValue?: string | number;
  label?: string;
  placeholder?: string;
  options: SelectOption[];
  disabled?: boolean;
  error?: string;
  hint?: string;
  size?: 'lg' | 'md' | 'sm';
  clearable?: boolean;
  searchable?: boolean;
}>(), {
  size: 'md',
  disabled: false,
  clearable: false,
  searchable: false,
});

const emit = defineEmits<{
  'update:modelValue': [value: string | number | null];
}>();

const isOpen = ref(false);
const searchQuery = ref('');

const selectedLabel = computed(() => {
  const selected = props.options.find(opt => opt.value === props.modelValue);
  return selected?.label ?? '';
});

const inputDisplayValue = computed(() => {
  return isOpen.value ? searchQuery.value : selectedLabel.value;
});

const filteredOptions = computed(() => {
  if (!props.searchable || !searchQuery.value) return props.options;
  return props.options.filter(opt =>
    opt.label.toLowerCase().includes(searchQuery.value.toLowerCase())
  );
});

const handleSelect = (value: string | number) => {
  emit('update:modelValue', value);
  isOpen.value = false;
  searchQuery.value = '';
};

const handleClear = () => {
  emit('update:modelValue', null);
  searchQuery.value = '';
};
</script>

<template>
  <div class="w-full">
    <!-- Label -->
    <label v-if="label" class="block text-xs font-semibold text-zinc-400 mb-1.5">
      {{ label }}
    </label>

    <!-- Regular Select (non-searchable) -->
    <div v-if="!searchable" class="relative">
      <!-- Select -->
      <select
        :value="modelValue"
        :disabled="disabled"
        @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
        :class="[
          'w-full bg-surface border rounded-lg text-text-main focus:outline-none transition-colors appearance-none cursor-pointer',
          'pr-10',
          // Size
          size === 'lg' && 'px-4 py-3 text-base',
          size === 'md' && 'px-3 py-2 text-sm',
          size === 'sm' && 'px-2.5 py-1.5 text-xs',
          // Border color
          error ? 'border-red-900/50 focus:border-red-600' : 'border-zinc-700 focus:border-primary',
          // Disabled
          disabled && 'opacity-50 cursor-not-allowed',
        ]"
      >
        <option v-if="placeholder || !modelValue" value="">{{ placeholder || '请选择' }}</option>
        <option v-for="opt in options" :key="opt.value" :value="opt.value" :disabled="opt.disabled">
          {{ opt.label }}
        </option>
      </select>

      <!-- Chevron Icon -->
      <svg class="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#FFFFFF">
        <path d="M480-360 280-560h400L480-360Z"/>
      </svg>

      <!-- Clear Button -->
      <button
        v-if="clearable && modelValue"
        type="button"
        @click="handleClear"
        class="absolute right-8 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Searchable Dropdown -->
    <div v-else class="relative">
      <!-- Search Input -->
      <div class="relative">
        <input
          type="text"
          :placeholder="placeholder || '搜索...'"
          :value="inputDisplayValue"
          @input="searchQuery = ($event.target as HTMLInputElement).value"
          @focus="isOpen = true"
          :disabled="disabled"
          :class="[
            'w-full bg-surface border rounded-lg text-text-main focus:outline-none transition-colors',
            'pr-10',
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

        <!-- Chevron Icon -->
        <svg class="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="#FFFFFF">
          <path d="M480-360 280-560h400L480-360Z"/>
        </svg>

        <!-- Clear Button -->
        <button
          v-if="clearable && modelValue"
          type="button"
          @click="handleClear"
          class="absolute right-8 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Dropdown Menu -->
      <div
        v-if="isOpen"
        class="absolute top-full left-0 right-0 mt-2 bg-surface border border-zinc-700 rounded-lg shadow-lg z-50 max-h-64 overflow-y-auto"
      >
        <div v-if="filteredOptions.length === 0" class="px-3 py-2 text-xs text-zinc-500 text-center">
          没有找到结果
        </div>
        <div v-for="opt in filteredOptions" :key="opt.value">
          <button
            type="button"
            :disabled="opt.disabled"
            @click="handleSelect(opt.value)"
            :class="[
              'w-full text-left px-3 py-2 text-sm transition-colors',
              'hover:bg-primary/20 focus:outline-none',
              modelValue === opt.value && 'bg-primary/30 text-primary font-semibold',
              opt.disabled && 'opacity-50 cursor-not-allowed hover:bg-surface'
            ]"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <!-- Close dropdown when clicking outside -->
      <div v-if="isOpen" @click="isOpen = false" class="fixed inset-0 z-40" />
    </div>

    <!-- Error message -->
    <p v-if="error" class="mt-1.5 text-xs text-red-400">{{ error }}</p>

    <!-- Hint text -->
    <p v-else-if="hint" class="mt-1.5 text-xs text-zinc-500">{{ hint }}</p>
  </div>
</template>
