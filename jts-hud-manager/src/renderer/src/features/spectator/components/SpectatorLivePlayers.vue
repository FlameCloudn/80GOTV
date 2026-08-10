<script setup lang="ts">
import BaseBadge from '@renderer/components/base/BaseBadge.vue';
import type { LivePlayer } from '../composables/useSpectator';
import BaseButton from '@renderer/components/base/BaseButton.vue';

defineProps<{
  gameState: any;
  livePlayers: LivePlayer[];
  ctPlayers: LivePlayer[];
  tPlayers: LivePlayer[];
}>();

defineEmits<{
  (e: 'quick-assign', name: string): void;
}>();
</script>

<template>
  <div>
    <h2 class="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-3">
      当前比赛选手
      <BaseBadge v-if="livePlayers.length" variant="zinc">{{ livePlayers.length }}</BaseBadge>
    </h2>

    <div v-if="!gameState" class="bg-zinc-800 border border-zinc-700 rounded-xl p-4 text-center">
      <div class="text-zinc-600 text-sm">正在等待 CS2 数据...</div>
      <div class="text-zinc-700 text-xs mt-1">请以观战者身份进入录像或比赛服务器。</div>
      <div class="text-zinc-700 text-xs mt-1">如果一直没有数据，请到设置中检查 GSI 配置。</div>
    </div>

    <div v-else-if="livePlayers.length === 0" class="bg-zinc-800 border border-zinc-700 rounded-xl p-4 text-center">
      <div class="text-zinc-600 text-sm">当前比赛中没有选手。</div>
    </div>

    <div v-else class="flex gap-4">
      <!-- CT side -->
      <div v-if="ctPlayers.length" class="flex-1">
        <div class="text-xs font-bold uppercase tracking-widest text-blue-500 mb-1.5 px-1">CT</div>
        <div class="grid grid-cols-2 gap-1.5">
          <button
            v-for="p in ctPlayers"
            :key="p.steamid"
            @click="$emit('quick-assign', p.name)"
            title="快速加入第一个空按键"
            class="flex items-center gap-2 bg-zinc-800 hover:bg-blue-900/30 border border-zinc-700 hover:border-blue-700/50 rounded-lg px-3 py-2 text-sm text-left transition-colors group"
          >
            <div class="w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0"></div>
            <span class="flex-1 truncate text-zinc-200 group-hover:text-blue-300">{{ p.name }}</span>
            <span class="text-xs shrink-0 font-mono">位置：{{ p.observerSlot === 0 ? '10' : p.observerSlot }}</span>
          </button>
        </div>
      </div>

      <!-- T side -->
      <div v-if="tPlayers.length" class="flex-1">
        <div class="text-xs font-bold uppercase tracking-widest text-yellow-500 mb-1.5 px-1">T</div>
        <div class="grid grid-cols-2 gap-1.5">
          <BaseButton
            v-for="p in tPlayers"
            :key="p.steamid"
            @click="$emit('quick-assign', p.name)"
            title="快速加入第一个空按键"
            class="flex items-center gap-2 bg-zinc-800 hover:bg-yellow-900/30 border border-zinc-700 hover:border-yellow-700/50 rounded-lg px-3 py-2 text-sm text-left transition-colors group"
          >
            <div class="w-1.5 h-1.5 rounded-full bg-yellow-500 shrink-0"></div>
            <span class="flex-1 truncate text-zinc-200 group-hover:text-yellow-300">{{ p.name }}</span>
            <span class="text-xs shrink-0 font-mono">位置：{{ p.observerSlot === 0 ? '10' : p.observerSlot }}</span>
          </BaseButton>
        </div>
      </div>
    </div>
  </div>
</template>
