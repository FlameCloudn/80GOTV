<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';
import BaseSelect from '@renderer/components/base/BaseSelect.vue';
import BaseCheckbox from '@renderer/components/base/BaseCheckbox.vue';
import AppIcon from '@renderer/components/ui/AppIcon.vue';
import { assetUrl } from '@renderer/utils/display';
import { showToast } from '@renderer/composables/useToasts';
import { countryOptions } from '@renderer/utils/countries';
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
    showToast(steamResolveError.value, 'error', { key: 'steam-profile' });
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
    showToast(steamResolveMessage.value, result.avatarUrl ? 'success' : 'info', { key: 'steam-profile' });
  } catch (error: any) {
    steamResolveError.value = error?.message || 'Steam 资料读取失败';
    showToast(steamResolveError.value, 'error', { key: 'steam-profile' });
  } finally {
    isResolvingSteam.value = false;
  }
};

const fileInputRef = ref<HTMLInputElement | null>(null);
const handleSubmit = () => { emit('submit', form.value, avatarFile.value); };
</script>

<template>
  <form id="playerForm" class="player-form" @submit.prevent="handleSubmit">
    <div class="identity">
      <div class="avatar-box">
        <div class="avatar-preview">
          <img v-if="avatarPreview" :src="avatarPreview" alt="" />
          <img v-else-if="form.avatar" :src="assetUrl(form.avatar)" alt="" />
          <span v-else class="avatar-empty">{{ (form.username || '?').slice(0, 1).toUpperCase() }}</span>
        </div>
        <button type="button" class="btn btn-sm avatar-btn" @click="fileInputRef?.click()"><AppIcon name="upload" />上传头像</button>
        <input ref="fileInputRef" type="file" accept="image/*" class="hidden-file" @change="onFileChange" />
      </div>
      <div class="identity-fields">
        <div class="steam-row">
          <BaseInput v-model="form.steamid" label="Steam64 ID" type="text" :disabled="lockSteamId" :invalid="Boolean(steamResolveError)" />
          <button type="button" class="btn steam-btn" :disabled="isResolvingSteam" title="用 Steam64 ID 自动填昵称和头像" @click="resolveSteamProfile">
            <AppIcon name="refresh" :class="{ spinning: isResolvingSteam }" />{{ isResolvingSteam ? '正在获取' : '自动获取' }}
          </button>
        </div>
        <p v-if="steamResolveMessage" class="steam-ok"><AppIcon name="check" />{{ steamResolveMessage }}</p>
        <BaseInput v-model="form.username" label="游戏昵称" type="text" />
      </div>
    </div>

    <div class="two-col">
      <BaseInput v-model="form.firstName" label="名字" type="text" />
      <BaseInput v-model="form.lastName" label="姓氏" type="text" />
    </div>
    <div class="two-col">
      <BaseSelect v-model="form.country" label="国家或地区" placeholder="未选择" :options="countrySelectOptions" />
      <BaseSelect v-model="form.team" label="所属战队" placeholder="未加入战队" :options="teamSelectOptions" :searchable="true" />
    </div>

    <div class="coach-row">
      <div>
        <b>设为教练</b>
        <p class="hint">教练不会出现在发送给导播 HUD 的选手数据里</p>
      </div>
      <BaseCheckbox v-model="form.isCoach" />
    </div>
  </form>
</template>

<style scoped>
.player-form { display: flex; flex-direction: column; gap: 16px; }
.identity { display: flex; gap: 18px; align-items: flex-start; }
.avatar-box { width: 132px; flex: none; display: flex; flex-direction: column; gap: 8px; }
.avatar-preview { width: 132px; height: 132px; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-lg); background: var(--bg-input); border: 1px solid var(--border-strong); }
.avatar-preview img { width: 100%; height: 100%; object-fit: cover; }
.avatar-empty { font: 800 40px/1 'Montserrat', sans-serif; color: var(--text-3); }
.avatar-btn { width: 100%; }
.hidden-file { display: none; }
.identity-fields { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.steam-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 8px; }
.steam-btn .icon.spinning { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.steam-ok { display: flex; align-items: center; gap: 6px; margin-top: -4px; font-size: 12px; color: #8fd3ad; }
.steam-ok .icon { width: 13px; height: 13px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.coach-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-radius: var(--radius-md); background: var(--bg-raised); border: 1px solid var(--border); }
.coach-row b { font-size: 13px; }
</style>
