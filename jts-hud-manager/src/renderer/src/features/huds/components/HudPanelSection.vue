<script setup lang="ts">
import { computed } from 'vue';
import type { PanelSection } from '../composables/useHudPanelView';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';
import BaseCheckbox from '@renderer/components/base/BaseCheckbox.vue';
import BaseSelect from '@renderer/components/base/BaseSelect.vue';

const props = defineProps<{
  section: PanelSection;
  sectionConfig: Record<string, any>;
  teams: any[];
  players: any[];
  matches: any[];
  showOnlyActivePlayers: boolean;
  liveDataAvailable: boolean;
  status: 'idle' | 'saving' | 'saved' | 'error' | undefined;
}>();

const emit = defineEmits<{
  save: [];
  'fire-action': [actionName: string, valueName: string];
  'upload-image': [inputName: string, file: File];
  'clear-image': [inputName: string];
  'upload-image-to-list': [inputName: string, file: File];
  'remove-image-from-list': [inputName: string, url: string];
  'toggle-active-players': [];
}>();

const hasNonActionInputs = computed(() => props.section.inputs.some(i => i.type !== 'action'));
const hasPlayerInput = computed(() => props.section.inputs.some(i => i.type === 'player'));

const onFileChange = (inputName: string, e: Event, multi: boolean) => {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  if (multi) emit('upload-image-to-list', inputName, file);
  else emit('upload-image', inputName, file);
  (e.target as HTMLInputElement).value = '';
};

// Convert select options to SelectOption[] format
const getSelectOptions = (input: any): SelectOption[] => {
  return (input.values || []).map((v: any) => ({
    value: v.name,
    label: v.label,
  }));
};

// Convert teams to SelectOption[]
const teamOptions = computed((): SelectOption[] =>
  props.teams.map(t => ({ value: t._id, label: t.name }))
);

// Convert players to SelectOption[]
const playerOptions = computed((): SelectOption[] =>
  props.players.map(p => ({
    value: p._id,
    label: `${p.username}${p.firstName || p.lastName ? ` (${p.firstName} ${p.lastName})` : ''}`,
  }))
);

// Convert matches to SelectOption[]
const matchOptions = computed((): SelectOption[] =>
  props.matches.map(m => ({
    value: m._id || m.id,
    label: `${m.left?.id ?? '待定'} 对阵 ${m.right?.id ?? '待定'} (${m.matchType})`,
  }))
);
</script>

<template>
  <div class="bg-zinc-800 border border-zinc-700 rounded-xl overflow-hidden">

    <!-- Section header -->
    <div class="px-5 py-3 border-b border-zinc-700 bg-surface/50 flex items-center justify-between">
      <h2 class="text-sm font-bold text-text-main tracking-tight">{{ section.label }}</h2>
      <label v-if="hasPlayerInput" class="flex items-center gap-2 cursor-pointer select-none group">
        <span class="text-xs text-zinc-500 group-hover:text-zinc-300 transition-colors">
          只显示当前比赛中的选手
        </span>
        <span
          class="relative inline-flex w-9 h-5 rounded-full transition-colors shrink-0"
          :class="showOnlyActivePlayers ? 'bg-emerald-600' : 'bg-zinc-700'"
          @click="emit('toggle-active-players')"
        >
          <span
            class="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform"
            :class="showOnlyActivePlayers ? 'translate-x-4' : 'translate-x-0'"
          />
        </span>
      </label>
    </div>

    <!-- Inputs -->
    <div class="p-5 grid grid-cols-2 gap-4">
      <div v-for="input in section.inputs" :key="input.name">

        <!-- TEXT -->
        <template v-if="input.type === 'text'">
          <BaseInput
            v-model="sectionConfig[input.name]"
            :label="input.label"
            :placeholder="input.label"
            size="md"
          />
        </template>

        <!-- CHECKBOX -->
        <template v-else-if="input.type === 'checkbox'">
          <BaseCheckbox
            v-model="sectionConfig[input.name]"
            :label="input.label"
            size="md"
          />
        </template>

        <!-- SELECT -->
        <template v-else-if="input.type === 'select'">
          <BaseSelect
            v-model="sectionConfig[input.name]"
            :label="input.label"
            :options="getSelectOptions(input)"
            size="md"
          />
        </template>

        <!-- PLAYER -->
        <template v-else-if="input.type === 'player'">
          <BaseSelect
            v-model="sectionConfig[input.name]"
            :label="input.label"
            :options="playerOptions"
            size="md"
          />
          <p v-if="showOnlyActivePlayers && !liveDataAvailable" class="mt-1.5 text-xs text-amber-500">
            未检测到实时比赛，当前显示全部选手。
          </p>
        </template>

        <!-- TEAM -->
        <template v-else-if="input.type === 'team'">
          <BaseSelect
            v-model="sectionConfig[input.name]"
            :label="input.label"
            :options="teamOptions"
            size="md"
          />
        </template>

        <!-- MATCH -->
        <template v-else-if="input.type === 'match'">
          <BaseSelect
            v-model="sectionConfig[input.name]"
            :label="input.label"
            :options="matchOptions"
            size="md"
          />
        </template>

        <!-- IMAGE (single) -->
        <template v-else-if="input.type === 'image'">
          <label class="block text-xs font-semibold text-zinc-400 mb-1.5">{{ input.label }}</label>
          <div class="flex items-center gap-3">
            <div v-if="sectionConfig?.[input.name]" class="relative w-12 h-12 border border-zinc-700 rounded-lg overflow-hidden bg-zinc-950 flex items-center justify-center shrink-0 group">
              <img :src="sectionConfig[input.name]" class="w-full h-full object-contain" />
              <button
                type="button"
                @click="emit('clear-image', input.name)"
                class="absolute inset-0 bg-black/60 hidden group-hover:flex items-center justify-center text-red-400"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            </div>
            <label class="cursor-pointer flex items-center gap-2 px-3 py-2 bg-surface border border-zinc-700 rounded-lg text-xs text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
              </svg>
              {{ sectionConfig?.[input.name] ? '替换图片' : '上传图片' }}
              <input type="file" accept="image/*" class="hidden" @change="onFileChange(input.name, $event, false)" />
            </label>
          </div>
        </template>

        <!-- IMAGES (multi) -->
        <template v-else-if="input.type === 'images'">
          <label class="block text-xs font-semibold text-zinc-400 mb-1.5">{{ input.label }}</label>
          <div class="space-y-2">
            <div v-if="(sectionConfig?.[input.name] as string[])?.length" class="flex flex-wrap gap-2">
              <div
                v-for="url in (sectionConfig[input.name] as string[])"
                :key="url"
                class="relative w-16 h-16 border border-zinc-700 rounded-lg overflow-hidden bg-zinc-950 group"
              >
                <img :src="url" class="w-full h-full object-contain" />
                <button
                  type="button"
                  @click="emit('remove-image-from-list', input.name, url)"
                  class="absolute inset-0 bg-black/60 hidden group-hover:flex items-center justify-center text-red-400"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                </button>
              </div>
            </div>
            <label class="cursor-pointer inline-flex items-center gap-2 px-3 py-2 bg-surface border border-zinc-700 rounded-lg text-xs text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
              </svg>
              添加图片
              <input type="file" accept="image/*" class="hidden" @change="onFileChange(input.name, $event, true)" />
            </label>
          </div>
        </template>

        <!-- ACTION -->
        <template v-else-if="input.type === 'action'">
          <label class="block text-xs font-semibold text-zinc-400 mb-2">{{ input.label }}</label>
          <div class="flex flex-wrap gap-2">
            <BaseButton
              v-for="val in input.values"
              :key="val.name"
              @click="emit('fire-action', input.name, val.name)"
              variant="secondary"
              class="bg-zinc-700!"
            >
              {{ val.label }}
            </BaseButton>
          </div>
        </template>

      </div>
    </div>

    <!-- Section footer -->
    <div
      v-if="hasNonActionInputs"
      class="px-5 py-3 border-t border-zinc-700 bg-surface/30 flex items-center justify-end gap-3"
    >
      <span v-if="status === 'saved'" class="text-emerald-400 text-xs flex items-center gap-1">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
        </svg>
        已发送！
      </span>
      <span v-else-if="status === 'error'" class="text-red-400 text-xs">发送失败</span>
      <BaseButton
        variant="primary"
        @click="emit('save')"
        :disabled="status === 'saving'"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
        </svg>
        {{ status === 'saving' ? '正在发送...' : '保存并发送' }}
      </BaseButton>
    </div>
  </div>
</template>
