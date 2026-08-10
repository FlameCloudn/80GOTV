<script setup lang="ts">
const props = defineProps<{
  ctScore: number;
  tScore: number;
  mapName: string;
  phaseEndsIn: number | string | undefined;
  phase: string | undefined;
}>();

const formatTime = (seconds: number | string | undefined): string => {
  const num = parseFloat(seconds as string);
  if (!Number.isFinite(num)) return '0:00';
  const remaining = Math.max(0, Math.ceil(num));
  const mins = Math.floor(remaining / 60);
  const secs = remaining % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
};

const phaseLabels: Record<string, string> = {
  freezetime: '准备时间',
  live: '进行中',
  over: '回合结束',
  paused: '已暂停',
  timeout_ct: 'CT 暂停',
  timeout_t: 'T 暂停',
  bomb: '炸弹阶段',
};

const formatPhase = (phase: string | undefined): string =>
  phase ? (phaseLabels[phase] ?? phase) : '等待中';
</script>

<template>
  <div class="bg-zinc-800 px-6 py-3 rounded-xl border border-zinc-700 flex justify-between items-center shadow-lg">
    <div class="flex flex-col items-center">
      <span class="text-blue-400 font-bold text-sm tracking-widest uppercase mb-1">反恐精英（CT）</span>
      <span class="text-5xl font-black text-text-main">{{ ctScore }}</span>
    </div>

    <div class="flex flex-col items-center px-8 border-x border-zinc-700">
      <span class="text-zinc-400 text-xs font-bold uppercase tracking-widest mb-1">地图：{{ mapName }}</span>
      <span class="text-4xl font-bold text-text-main tracking-tight">
        {{ formatTime(phaseEndsIn) }}
      </span>
      <span class="text-zinc-500 text-xs uppercase mt-1">{{ formatPhase(phase) }}</span>
    </div>

    <div class="flex flex-col items-center">
      <span class="text-yellow-400 font-bold text-sm tracking-widest uppercase mb-1">恐怖分子（T）</span>
      <span class="text-5xl font-black text-text-main">{{ tScore }}</span>
    </div>
  </div>
</template>
