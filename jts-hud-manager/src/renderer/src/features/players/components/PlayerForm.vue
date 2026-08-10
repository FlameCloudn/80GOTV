<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';
import BaseSelect from '@renderer/components/base/BaseSelect.vue';
import BaseCheckbox from '@renderer/components/base/BaseCheckbox.vue';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import { countryOptions } from '@renderer/utils/countries';
import RefreshIcon from '@renderer/assets/icons/RefreshIcon.vue';
import { API_URL } from '@renderer/index';

const props = defineProps<{
  initialData: any;
  teams: any[];
  isEditing: boolean;
  lockSteamId?: boolean;
}>();

const emit = defineEmits(['submit']);
const form = ref({ ...props.initialData });
const avatarFile = ref<File | null>(null);
const avatarPreview = ref<string | null>(null);
const isResolvingSteam = ref(false);
const steamResolveError = ref('');
const steamResolveMessage = ref('');
const resolvedSteamId = ref('');

const clearBlobPreview = () => {
  if (avatarPreview.value?.startsWith('blob:')) URL.revokeObjectURL(avatarPreview.value);
};

watch(() => props.initialData, (newData) => {
  clearBlobPreview();
  form.value = { ...newData };
  avatarFile.value = null;
  avatarPreview.value = null;
  steamResolveError.value = '';
  steamResolveMessage.value = '';
  resolvedSteamId.value = '';
}, { deep: true });

watch(() => form.value.steamid, (value) => {
  if (!resolvedSteamId.value || String(value || '').trim() === resolvedSteamId.value) return;
  form.value.steamAvatarUrl = '';
  resolvedSteamId.value = '';
  steamResolveMessage.value = '';
  if (avatarPreview.value && !avatarPreview.value.startsWith('blob:')) avatarPreview.value = null;
});

// Convert data to SelectOption[] format
const countrySelectOptions = computed((): SelectOption[] =>
  countryOptions.map(c => ({ value: c.code, label: `${c.name} (${c.code})` }))
);

const teamSelectOptions = computed((): SelectOption[] =>
  props.teams.map(t => ({ value: t._id, label: t.name }))
);

const onFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement;
  if (target.files?.length) {
    clearBlobPreview();
    avatarFile.value = target.files[0];
    avatarPreview.value = URL.createObjectURL(target.files[0]);
    form.value.steamAvatarUrl = '';
    resolvedSteamId.value = '';
    steamResolveMessage.value = '';
  }
};

const resolveSteamProfile = async () => {
  const steamid = String(form.value.steamid || '').trim();
  form.value.steamid = steamid;
  steamResolveError.value = '';
  steamResolveMessage.value = '';

  if (!/^\d{17}$/.test(steamid)) {
    steamResolveError.value = '请输入 17 位数字的 Steam64 ID';
    return;
  }

  isResolvingSteam.value = true;
  try {
    const response = await fetch(`${API_URL}/players/steam-profile/${steamid}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Steam 资料读取失败');

    form.value.username = result.username || form.value.username;
    form.value.steamAvatarUrl = result.avatarUrl || '';
    resolvedSteamId.value = steamid;
    avatarFile.value = null;
    clearBlobPreview();
    avatarPreview.value = result.avatarUrl || null;
    steamResolveMessage.value = result.avatarUrl
      ? '已获取 Steam 昵称和头像'
      : '已获取 Steam 昵称，公开头像不可用';
  } catch (error: any) {
    steamResolveError.value = error?.message || 'Steam 资料读取失败';
  } finally {
    isResolvingSteam.value = false;
  }
};

const fileInputRef = ref<HTMLInputElement | null>(null);
const handleSubmit = () => { emit('submit', form.value, avatarFile.value); };
</script>

<template>
  <form id="playerForm" @submit.prevent="handleSubmit" class="p-6 space-y-6">

    <!-- Avatar + Primary Identity -->
    <div class="flex gap-6 items-start">

      <!-- Avatar upload -->
      <div class="flex flex-col items-center gap-2 shrink-0">
        <div class="w-36 h-36 rounded-xl overflow-hidden border-2 border-zinc-700 bg-surface flex items-center justify-center">
          <img v-if="avatarPreview" :src="avatarPreview" class="w-full h-full object-cover" />
          <img v-else-if="form.avatar" :src="`http://localhost:1349${form.avatar}`" class="w-full h-full object-cover" />
          <span v-else class="text-zinc-600 text-6xl select-none">?</span>
        </div>
        <BaseButton @click="fileInputRef?.click()" class="w-full justify-center ">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
          上传头像
        </BaseButton>
        <input ref="fileInputRef" type="file" accept="image/*" @change="onFileChange" class="hidden" />
      </div>

      <!-- Steam ID + Username -->
      <div class="flex-1 space-y-4">
        <div>
          <BaseInput
            v-model="form.steamid"
            label="Steam ID 64"
            type="text"
            :disabled="lockSteamId"
            size="md"
          />
          <div class="mt-2 flex items-center justify-between gap-3">
            <p v-if="steamResolveError" class="text-xs text-red-400">{{ steamResolveError }}</p>
            <p v-else-if="steamResolveMessage" class="text-xs text-emerald-400">{{ steamResolveMessage }}</p>
            <span v-else></span>
            <BaseButton
              size="sm"
              class="shrink-0"
              :disabled="isResolvingSteam"
              @click="resolveSteamProfile"
            >
              <RefreshIcon class="w-3.5 h-3.5" :class="isResolvingSteam && 'animate-spin'" />
              {{ isResolvingSteam ? '正在获取' : '自动获取' }}
            </BaseButton>
          </div>
        </div>
        <BaseInput
          v-model="form.username"
          label="游戏昵称"
          type="text"
          size="md"
        />
      </div>
    </div>

    <div class="border-t border-zinc-700/50"></div>

    <!-- Name row -->
    <div class="grid grid-cols-2 gap-4">
      <BaseInput
        v-model="form.firstName"
        label="名字"
        type="text"
        size="md"
      />
      <BaseInput
        v-model="form.lastName"
        label="姓氏"
        type="text"
        size="md"
      />
    </div>

    <!-- Country + Team row -->
    <div class="grid grid-cols-2 gap-4">
      <BaseSelect
        v-model="form.country"
        label="国家或地区"
        placeholder="未选择"
        :options="countrySelectOptions"
        size="md"
      />
      <BaseSelect
        v-model="form.team"
        label="所属战队"
        placeholder="未加入战队"
        :options="teamSelectOptions"
        :searchable="true"
        size="md"
      />
    </div>

    <!-- Coach toggle -->
    <div class="p-4 rounded-lg border border-zinc-700 bg-surface/50">
      <div class="flex items-center justify-between">
        <div>
          <span class="text-sm font-semibold text-zinc-200">设为教练</span>
          <p class="text-xs text-zinc-500 mt-0.5">教练不会出现在发送给导播 HUD 的选手数据中</p>
        </div>
        <BaseCheckbox
          v-model="form.isCoach"
          size="md"
        />
      </div>
    </div>

  </form>
</template>
