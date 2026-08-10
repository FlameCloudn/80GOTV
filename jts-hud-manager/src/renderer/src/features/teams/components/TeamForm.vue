<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';
import BaseSelect from '@renderer/components/base/BaseSelect.vue';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import { countryOptions } from '@renderer/utils/countries';
import { API_URL } from '@renderer/index';

const props = defineProps<{ initialData: any; isEditing: boolean; players: any[]; }>();
const emit = defineEmits(['submit']);
const form = ref({ ...props.initialData });
const logoFile = ref<File | null>(null);
const logoPreview = ref<string | null>(null);
const playerSearch = ref('');
const baseUrl = API_URL.replace('/api', '');

const countrySelectOptions = computed((): SelectOption[] =>
  countryOptions.map(c => ({ value: c.code, label: `${c.name} (${c.code})` }))
);

watch(() => props.initialData, (newData) => {
  form.value = { ...newData, playerIds: [...(newData.playerIds || [])] };
  logoPreview.value = null;
  playerSearch.value = '';
}, { deep: true });

const filteredPlayers = computed(() => {
  const query = playerSearch.value.trim().toLowerCase();
  if (!query) return props.players;
  return props.players.filter(player =>
    [player.username, player.firstName, player.lastName, player.steamid]
      .some(value => String(value || '').toLowerCase().includes(query))
  );
});

const isPlayerSelected = (id: string) => (form.value.playerIds || []).includes(id);

const togglePlayer = (id: string) => {
  const selected = new Set<string>(form.value.playerIds || []);
  if (selected.has(id)) selected.delete(id);
  else selected.add(id);
  form.value.playerIds = [...selected];
};

const playerStatus = (player: any) => {
  if (player.team === form.value._id) return '本队选手';
  if (player.team) return '目前在其他战队';
  return '未加入战队';
};

const fileInputRef = ref<HTMLInputElement | null>(null);

const onFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement;
  if (target.files?.length) {
    logoFile.value = target.files[0];
    logoPreview.value = URL.createObjectURL(target.files[0]);
  }
};
</script>

<template>
  <form id="teamForm" @submit.prevent="emit('submit', form, logoFile)" class="p-6 space-y-6">

    <!-- Logo + Primary Info -->
    <div class="flex gap-6 items-start">

      <!-- Logo upload -->
      <div class="flex flex-col items-center gap-2 shrink-0">
        <div class="w-36 h-36 rounded-xl overflow-hidden border-2 border-zinc-700 bg-surface flex items-center justify-center p-3">
          <img v-if="logoPreview" :src="logoPreview" class="w-full h-full object-contain" />
          <img v-else-if="form.logo" :src="`http://localhost:1349${form.logo}`" class="w-full h-full object-contain" />
          <span v-else class="text-zinc-600 text-6xl font-black select-none">T</span>
        </div>
        <BaseButton @click="fileInputRef?.click()" class="w-full justify-center">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
          上传队标
        </BaseButton>
        <input ref="fileInputRef" type="file" accept="image/*" @change="onFileChange" class="hidden" />
      </div>

      <!-- Team Name + Short Name -->
      <div class="flex-1 space-y-4">
        <BaseInput
          v-model="form.name"
          label="战队名称"
          type="text"
          size="md"
        />
        <BaseInput
          v-model="form.shortName"
          label="战队简称"
          type="text"
          placeholder="例如：NAVI"
          size="md"
        />
      </div>
    </div>

    <div class="border-t border-zinc-700/50"></div>

    <!-- Country -->
    <BaseSelect
      v-model="form.country"
      label="国家或地区"
      placeholder="未选择"
      :options="countrySelectOptions"
      size="md"
    />

    <template v-if="isEditing">
      <div class="border-t border-zinc-700/50"></div>

      <section class="space-y-3">
        <div class="flex items-center justify-between gap-3">
          <h3 class="text-sm font-bold text-zinc-200">战队选手</h3>
          <span class="text-xs text-zinc-500">已选择 {{ (form.playerIds || []).length }} 人</span>
        </div>

        <BaseInput
          v-model="playerSearch"
          type="text"
          placeholder="搜索昵称、姓名或 Steam64 ID"
          size="md"
        />

        <div class="max-h-64 overflow-y-auto border border-zinc-700 rounded-lg divide-y divide-zinc-800 bg-zinc-950/30">
          <label
            v-for="player in filteredPlayers"
            :key="player._id"
            class="min-h-14 px-3 py-2 flex items-center gap-3 cursor-pointer hover:bg-zinc-800/70 transition-colors"
          >
            <input
              type="checkbox"
              class="size-4 shrink-0 accent-blue-500"
              :checked="isPlayerSelected(player._id)"
              @change="togglePlayer(player._id)"
            />
            <div class="size-9 shrink-0 overflow-hidden rounded-md bg-zinc-800 flex items-center justify-center">
              <img
                v-if="player.avatar"
                :src="`${baseUrl}${player.avatar}`"
                class="size-full object-cover"
              />
              <span v-else class="text-xs font-bold text-zinc-500">{{ player.username?.slice(0, 1) || '?' }}</span>
            </div>
            <div class="min-w-0 flex-1">
              <div class="text-sm font-semibold text-zinc-200 truncate">{{ player.username || '未命名选手' }}</div>
              <div class="text-xs text-zinc-500 truncate">{{ player.steamid || '没有 Steam64 ID' }}</div>
            </div>
            <span
              class="text-xs shrink-0"
              :class="player.team && player.team !== form._id ? 'text-amber-400' : 'text-zinc-500'"
            >
              {{ playerStatus(player) }}
            </span>
          </label>

          <div v-if="filteredPlayers.length === 0" class="h-20 flex items-center justify-center text-sm text-zinc-600">
            没有找到选手
          </div>
        </div>
      </section>
    </template>

  </form>
</template>
