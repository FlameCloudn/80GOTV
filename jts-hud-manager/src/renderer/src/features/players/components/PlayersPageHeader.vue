<script setup lang="ts">
import BaseButton from '../../../components/base/BaseButton.vue';

defineProps<{
  playersCount: number;
}>();

defineEmits<{
  import: [];
  export: [];
  deleteAll: [];
  add: [];
}>();
</script>

<template>
  <div class="flex justify-between items-center mb-6">
    <div>
      <h1 class="text-2xl font-bold text-text-main tracking-tight">选手</h1>
      <p class="text-zinc-400 text-sm mt-1">管理选手资料、头像和所属战队。</p>
    </div>
    <div class="flex gap-3">
      <BaseButton @click="$emit('import')">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        导入
      </BaseButton>
      <BaseButton @click="$emit('export')">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
        导出
      </BaseButton>
      <BaseButton variant="danger" :disabled="playersCount === 0" @click="$emit('deleteAll')">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
        全部删除
      </BaseButton>
      <BaseButton variant="primary" @click="$emit('add')">
        + 添加选手
      </BaseButton>
    </div>
  </div>
</template>
