<script setup lang="ts">
import { computed } from 'vue';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import BaseSelect from '@renderer/components/base/BaseSelect.vue';
import CloseIcon from '@renderer/assets/icons/CloseIcon.vue';
import type { LivePlayer } from '../composables/useSpectator';
import BaseButton from '@renderer/components/base/BaseButton.vue';

const props = defineProps<{
  slots: Record<number, string>;
  livePlayers: LivePlayer[];
  allPlayerNames: string[];
  sideForName: (name: string) => 'CT' | 'T' | null;
  slotKeys: Record<number, string>;
}>();

defineEmits<{
  (e: 'clear-slot', slot: number): void;
  (e: 'fill-from-cs2'): void;
}>();

// Build select options for each slot
const getSlotOptions = (slot: number): SelectOption[] => {
  const options: SelectOption[] = [];

  if (props.livePlayers.length) {
    options.push(...props.livePlayers.map(p => ({ value: p.name, label: p.name })));
  }

  // Add currently saved player if not in live list
  if (props.slots[slot] && !props.allPlayerNames.includes(props.slots[slot])) {
    options.push({ value: props.slots[slot], label: props.slots[slot] });
  }

  return options;
};

const slotOptionsMap = computed(() => {
  const map: Record<number, SelectOption[]> = {};
  for (let i = 1; i <= 10; i++) {
    map[i] = getSlotOptions(i);
  }
  return map;
});
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-sm font-semibold text-zinc-400 uppercase tracking-wider">数字键对应选手</h2>
      <BaseButton
        v-if="livePlayers.length > 0"
        size="sm"
        @click="$emit('fill-from-cs2')"
        title="根据 CS2 当前观战位置自动填写"
      >
        从 CS2 自动填写
      </BaseButton>
    </div>

    <!-- Keyboard row -->
    <div class="grid grid-cols-10 gap-1.5">
      <div v-for="slot in 10" :key="slot" class="flex flex-col gap-1.5">

        <!-- Keycap -->
        <div
          class="relative h-22 flex flex-col items-center justify-center gap-0.5 bg-zinc-800 border-2 rounded-xl pt-2 pb-2.5 px-1 transition-colors"
          style="box-shadow: 0 3px 0 0 rgba(0,0,0,0.55)"
          :class="slots[slot]
            ? sideForName(slots[slot]) === 'CT'
              ? 'border-blue-600/70'
              : sideForName(slots[slot]) === 'T'
                ? 'border-yellow-600/70'
                : 'border-zinc-600'
            : 'border-zinc-700'"
        >
          <!-- Clear × -->
          <button
            v-if="slots[slot]"
            @click="$emit('clear-slot', slot)"
            class="absolute top-0.5 right-0.5 text-zinc-600 hover:text-red-400 transition-colors"
            title="清空这个按键"
          >
            <CloseIcon name="close" class="size-6" />
          </button>

          <!-- Key character -->
          <span class="text-4xl font-bold text-text-main leading-none select-none absolute top-1/2 -translate-y-1/2">{{ slotKeys[slot] }}</span>

          <!-- Player name on keycap -->
          <span
            v-if="slots[slot]"
            class="text-sm absolute bottom-1 font-semibold leading-tight text-center w-full px-0.5 truncate mt-0.5 select-none"
            :class="sideForName(slots[slot]) === 'CT' ? 'text-blue-300' : 'text-yellow-300'"
            :title="slots[slot]"
          >{{ slots[slot] }}</span>
        </div>

        <!-- Compact player select below the keycap -->
        <BaseSelect
          v-model="slots[slot]"
          :options="slotOptionsMap[slot]"
          size="sm"
          :class="slots[slot]
            ? sideForName(slots[slot]) === 'CT' ? 'text-blue-300' : 'text-yellow-300'
            : 'text-zinc-400'"
        />

      </div>
    </div>
  </div>
</template>
