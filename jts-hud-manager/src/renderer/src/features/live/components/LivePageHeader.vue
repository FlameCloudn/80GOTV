<script setup lang="ts">
defineProps<{
  isConnected: boolean;
}>();
</script>

<template>
  <div class="flex justify-between items-center mb-6">
    <div>
      <h1 class="text-2xl font-bold text-text-main flex items-center gap-3">
        实时比赛数据
        <span
          v-if="isConnected"
          class="px-2 py-0.5 bg-emerald-500/20 text-emerald-400 text-xs rounded-full border border-emerald-500/30"
        >GSI 已连接</span>
        <span
          v-else
          class="px-2 py-0.5 bg-red-500/20 text-red-400 text-xs rounded-full border border-red-500/30"
        >未连接</span>
      </h1>
      <p class="text-zinc-400 text-sm mt-1">查看 CS2 实时状态，并快速补充选手资料。</p>
    </div>
  </div>
</template>
