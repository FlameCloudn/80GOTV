<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';
import BaseSelect from '@renderer/components/base/BaseSelect.vue';
import AppIcon from '@renderer/components/ui/AppIcon.vue';
import { assetUrl } from '@renderer/utils/display';
import { countryOptions } from '@renderer/utils/countries';

const props = defineProps<{ initialData: any; isEditing: boolean; players: any[]; }>();
const emit = defineEmits(['submit']);
const form = ref({ ...props.initialData });
const logoFile = ref<File | null>(null);
const logoPreview = ref<string | null>(null);
const playerSearch = ref('');

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
  <form id="teamForm" class="team-form" @submit.prevent="emit('submit', form, logoFile)">
    <div class="identity">
      <div class="logo-box">
        <div class="logo-preview">
          <img v-if="logoPreview" :src="logoPreview" alt="" />
          <img v-else-if="form.logo" :src="assetUrl(form.logo)" alt="" />
          <span v-else class="logo-empty num">{{ (form.shortName || form.name || 'T').slice(0, 2).toUpperCase() }}</span>
        </div>
        <button type="button" class="btn btn-sm logo-btn" @click="fileInputRef?.click()"><AppIcon name="upload" />上传队标</button>
        <input ref="fileInputRef" type="file" accept="image/*" class="hidden-file" @change="onFileChange" />
      </div>
      <div class="identity-fields">
        <BaseInput v-model="form.name" label="战队名称" type="text" />
        <BaseInput v-model="form.shortName" label="战队简称" type="text" placeholder="例如：NAVI" />
        <BaseSelect v-model="form.country" label="国家或地区" placeholder="未选择" :options="countrySelectOptions" />
      </div>
    </div>

    <section v-if="isEditing" class="roster">
      <div class="roster-head">
        <h3>战队选手</h3>
        <span class="hint">已选择 <b class="num">{{ (form.playerIds || []).length }}</b> 人</span>
      </div>
      <BaseInput v-model="playerSearch" type="text" placeholder="搜索昵称、姓名或 Steam64 ID" />
      <div class="roster-list">
        <label v-for="player in filteredPlayers" :key="player._id" class="roster-row" :class="{ picked: isPlayerSelected(player._id) }">
          <input type="checkbox" class="check" :checked="isPlayerSelected(player._id)" @change="togglePlayer(player._id)" />
          <span class="avatar">
            <img v-if="player.avatar" :src="assetUrl(player.avatar)" alt="" />
            <template v-else>{{ player.username?.slice(0, 1) || '?' }}</template>
          </span>
          <span class="roster-main">
            <b>{{ player.username || '未命名选手' }}</b>
            <small class="num">{{ player.steamid || '没有 Steam64 ID' }}</small>
          </span>
          <span class="roster-state" :class="{ other: player.team && player.team !== form._id }">{{ playerStatus(player) }}</span>
        </label>
        <div v-if="filteredPlayers.length === 0" class="roster-empty">没有找到选手</div>
      </div>
    </section>
  </form>
</template>

<style scoped>
.team-form { display: flex; flex-direction: column; gap: 18px; }
.identity { display: flex; gap: 18px; align-items: flex-start; }
.logo-box { width: 132px; flex: none; display: flex; flex-direction: column; gap: 8px; }
.logo-preview { width: 132px; height: 132px; display: grid; place-items: center; padding: 12px; border-radius: var(--radius-lg); background: var(--bg-input); border: 1px solid var(--border-strong); }
.logo-preview img { width: 100%; height: 100%; object-fit: contain; }
.logo-empty { font-size: 34px; font-weight: 800; color: var(--text-3); }
.logo-btn { width: 100%; }
.hidden-file { display: none; }
.identity-fields { flex: 1; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.roster { display: flex; flex-direction: column; gap: 10px; padding-top: 16px; border-top: 1px solid var(--border); }
.roster-head { display: flex; align-items: center; justify-content: space-between; }
.roster-head h3 { font-size: 14px; font-weight: 700; }
.roster-head b { color: var(--accent); }
.roster-list { max-height: 260px; overflow-y: auto; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-input); }
.roster-row { display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 6px 12px; border-bottom: 1px solid var(--border); cursor: pointer; }
.roster-row:last-child { border-bottom: none; }
.roster-row:hover { background: var(--bg-hover); }
.roster-row.picked { background: var(--accent-soft); }
.check { width: 14px; height: 14px; accent-color: var(--accent); flex: none; }
.avatar { width: 34px; height: 34px; flex: none; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-md); background: var(--bg-raised); color: var(--text-3); font-weight: 700; }
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.roster-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.roster-main b { font-size: 13px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.roster-main small { font-size: 11px; color: var(--text-3); }
.roster-state { flex: none; font-size: 12px; color: var(--text-3); }
.roster-state.other { color: var(--gold); }
.roster-empty { padding: 24px; text-align: center; font-size: 13px; color: var(--text-3); }
</style>
