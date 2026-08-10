<script setup lang="ts">
import BaseButton from './BaseButton.vue';

defineProps<{
  isOpen: boolean;
  title: string;
  formId?: string; // ID of the form inside the slot to trigger submit
  maxWidthClass?: string;
}>();

defineEmits(['close', 'cancel']);
</script>

<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
    <div :class="['bg-zinc-800 rounded-xl border border-zinc-700 w-full shadow-2xl overflow-hidden flex flex-col max-h-[90vh]', maxWidthClass || 'max-w-md']">
      
      <div class="p-6 border-b border-zinc-700 flex justify-between items-center bg-zinc-800/50">
        <h2 class="text-xl font-bold text-text-main">{{ title }}</h2>
        <BaseButton @click="$emit('close')" variant="ghost" size="sm">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </BaseButton>
      </div>
      
      <div class="overflow-y-auto flex-1 custom-scrollbar">
        <slot></slot>
      </div>

      <div class="p-6 border-t border-zinc-700 bg-zinc-800/50 flex gap-3">
        <BaseButton 
          @click="$emit('cancel')" 
          class="flex-1 justify-center"
        >
          取消
        </BaseButton>
        <BaseButton 
          :form="formId"
          type="submit" 
          variant="primary"
          class="flex-1 justify-center"
        >
          保存更改
        </BaseButton>
      </div>
      
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: #3f3f46; border-radius: 10px; }
</style>
