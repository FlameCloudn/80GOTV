<script setup lang="ts">
import { computed } from 'vue';
import type { GsiPlayer } from '../composables/useLiveView';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import BaseBadge from '@renderer/components/base/BaseBadge.vue';

const props = defineProps<{
  side: 'CT' | 'T';
  players: GsiPlayer[];
}>();

const emit = defineEmits<{
  edit: [player: GsiPlayer];
  addAll: [];
}>();

const theme = computed(() =>
  props.side === 'CT'
    ? {
        border: 'border-blue-900/50',
        header: 'bg-blue-900/30 border-blue-900/50',
        label: 'text-blue-400',
        addAllBtn: 'bg-blue-700/40 border-blue-600/50 text-blue-300 hover:bg-blue-600 hover:text-text-main',
        editHover: 'hover:bg-blue-600',
      }
    : {
        border: 'border-yellow-900/50',
        header: 'bg-yellow-900/30 border-yellow-900/50',
        label: 'text-yellow-400',
        addAllBtn: 'bg-yellow-700/40 border-yellow-600/50 text-yellow-300 hover:bg-yellow-600 hover:text-text-main',
        editHover: 'hover:bg-yellow-600',
      }
);

const sideLabel = computed(() => props.side === 'CT' ? 'CT 选手' : 'T 选手');
</script>

<template>
  <div class="bg-zinc-800/50 rounded-xl overflow-hidden" :class="`border ${theme.border}`">
    <div class="px-4 py-3 border-b flex justify-between items-center" :class="theme.header">
      <span class="font-bold text-sm uppercase" :class="theme.label">{{ sideLabel }}</span>
      <button
        @click="emit('addAll')"
        class="px-3 py-1 rounded text-xs font-bold border transition-colors"
        :class="theme.addAllBtn"
      >全部加入战队</button>
    </div>

    <div class="p-4 space-y-1.5">
      <div
        v-for="player in players"
        :key="player.steamid"
        class="rounded-lg p-3 flex justify-between items-center transition-colors"
        :class="player.isCoach
          ? 'bg-red-950/20 border border-red-700/60 hover:border-red-500'
          : 'bg-surface border border-zinc-700 hover:border-primary'"
      >
        <div>
          <div class="font-bold flex items-center gap-2" :class="player.isCoach ? 'text-red-300' : 'text-text-main'">
            {{ player.name }}
            <BaseBadge v-if="player.isCoach" variant="red">教练</BaseBadge>
            <BaseBadge v-else-if="player.inDB" variant="emerald">已录入</BaseBadge>
          </div>
          <div class="text-xs text-zinc-400 mt-1">击杀：{{ player.stats?.kills || 0 }} · 死亡：{{ player.stats?.deaths || 0 }}</div>
        </div>
        <BaseButton
          @click="emit('edit', player)"
          variant="secondary"
          :class="player.isCoach && 'hover:bg-red-600'"
        >编辑</BaseButton>
      </div>
    </div>
  </div>
</template>
