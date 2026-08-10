<script setup lang="ts">
import { ref, computed } from 'vue';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';
import { API_URL } from '../../../index';

const props = defineProps<{
  isOpen: boolean;
  side: 'CT' | 'T' | null;
  teams: any[];
  playerCount: number;
  selectedTeamId: string;
  isAdding: boolean;
}>();

const emit = defineEmits<{
  'update:selectedTeamId': [value: string];
  close: [];
  confirm: [];
}>();

const baseUrl = API_URL.replace('/api', '');
const searchQuery = ref('');

const filteredTeams = computed(() => {
  if (!searchQuery.value) return props.teams;
  
  const query = searchQuery.value.toLowerCase();
  return props.teams.filter(team => 
    team.name.toLowerCase().includes(query)
  );
});
</script>

<template>
  <div
    v-if="isOpen"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
  >
    <div class="bg-zinc-800 rounded-xl border border-zinc-700 w-full max-w-sm shadow-2xl overflow-hidden flex flex-col">
      <div class="p-6 border-b border-zinc-700 flex justify-between items-center bg-zinc-800/50">
        <h2 class="text-xl font-bold text-text-main">把全部 {{ side }} 选手加入战队</h2>
        <button @click="emit('close')" class="text-zinc-400 hover:text-text-main transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="p-6 space-y-4">
        <p class="text-zinc-400 text-sm">
          选择一支战队，将当前 {{ playerCount }} 名选手全部加入。已录入的选手会更新所属战队。
        </p>
        <BaseInput
          v-model="searchQuery"
          type="search"
          placeholder="搜索战队..."
        />
        <div v-if="teams.length === 0" class="text-zinc-500 text-sm text-center py-4">
          还没有战队，请先创建一支战队。
        </div>
        <div v-else-if="filteredTeams.length === 0" class="text-zinc-500 text-sm text-center py-4">
          没有找到符合条件的战队。
        </div>
        <div v-else class="space-y-2 max-h-60 overflow-y-auto">
          <div
            v-for="team in filteredTeams"
            :key="team._id"
            @click="emit('update:selectedTeamId', team._id)"
            :class="[
              'flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
              selectedTeamId === team._id
                ? 'border-primary bg-primary/10 text-text-main'
                : 'border-zinc-700 bg-surface text-zinc-300 hover:border-zinc-500'
            ]"
          >
            <img v-if="team.logo" :src="`${baseUrl}${team.logo}`" class="w-8 h-8 rounded object-contain bg-zinc-800" />
            <div v-else class="w-8 h-8 rounded bg-zinc-700 flex items-center justify-center text-zinc-400 text-xs font-bold">?</div>
            <span class="font-semibold">{{ team.name }}</span>
            <svg v-if="selectedTeamId === team._id" xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 ml-auto text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
            </svg>
          </div>
        </div>
      </div>

      <div class="p-4 border-t border-zinc-700 bg-zinc-800/50 flex gap-3">
        <BaseButton @click="emit('close')" variant="secondary" class="flex-1 justify-center">
          取消
        </BaseButton>
        <BaseButton
          @click="emit('confirm')"
          :disabled="!selectedTeamId || isAdding"
          variant="primary"
          class="flex-1 justify-center"
        >
          <svg v-if="isAdding" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
          </svg>
          {{ isAdding ? '正在添加...' : '添加全部选手' }}
        </BaseButton>
      </div>
    </div>
  </div>
</template>
