<script setup lang="ts">
import { computed } from 'vue';
import type { PanelSection } from '../composables/useHudPanelView';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import AppIcon from '@renderer/components/ui/AppIcon.vue';
import { boLabel } from '@renderer/utils/display';
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
// 比赛选项写“队名 VS 队名 · BO3”（原来显示的是战队编号）
const teamNameOf = (id?: string | null) => (id ? props.teams.find(t => t._id === id)?.name ?? '未知战队' : '待定');
const matchOptions = computed((): SelectOption[] =>
  props.matches.map(m => ({
    value: m._id || m.id,
    label: `${teamNameOf(m.left?.id)} VS ${teamNameOf(m.right?.id)} · ${boLabel(m.matchType) || m.matchType}`,
  }))
);
</script>

<template>
  <section class="panel hud-section">
    <header class="section-head">
      <h2>{{ section.label }}</h2>
      <label v-if="hasPlayerInput" class="active-toggle">
        <span>只显示当前比赛中的选手</span>
        <button type="button" class="switch" :class="{ on: showOnlyActivePlayers }" role="switch" :aria-checked="showOnlyActivePlayers" @click="emit('toggle-active-players')" />
      </label>
    </header>

    <div class="section-grid">
      <div v-for="input in section.inputs" :key="input.name" class="section-field" :class="{ wide: input.type === 'action' || input.type === 'images' }">
        <BaseInput v-if="input.type === 'text'" v-model="sectionConfig[input.name]" :label="input.label" :placeholder="input.label" />
        <BaseCheckbox v-else-if="input.type === 'checkbox'" v-model="sectionConfig[input.name]" :label="input.label" class="checkbox-field" />
        <BaseSelect v-else-if="input.type === 'select'" v-model="sectionConfig[input.name]" :label="input.label" :options="getSelectOptions(input)" />
        <template v-else-if="input.type === 'player'">
          <BaseSelect v-model="sectionConfig[input.name]" :label="input.label" :options="playerOptions" />
          <p v-if="showOnlyActivePlayers && !liveDataAvailable" class="field-note">没检测到实时比赛，先显示全部选手。</p>
        </template>
        <BaseSelect v-else-if="input.type === 'team'" v-model="sectionConfig[input.name]" :label="input.label" :options="teamOptions" />
        <BaseSelect v-else-if="input.type === 'match'" v-model="sectionConfig[input.name]" :label="input.label" :options="matchOptions" />

        <div v-else-if="input.type === 'image'" class="field">
          <span class="field-label">{{ input.label }}</span>
          <div class="image-row">
            <div v-if="sectionConfig?.[input.name]" class="image-thumb">
              <img :src="sectionConfig[input.name]" alt="" />
              <button type="button" class="image-remove" title="清除这张图" @click="emit('clear-image', input.name)"><AppIcon name="x" /></button>
            </div>
            <label class="btn btn-sm upload-label">
              <AppIcon name="image" />{{ sectionConfig?.[input.name] ? '替换图片' : '上传图片' }}
              <input type="file" accept="image/*" class="hidden-file" @change="onFileChange(input.name, $event, false)" />
            </label>
          </div>
        </div>

        <div v-else-if="input.type === 'images'" class="field">
          <span class="field-label">{{ input.label }}</span>
          <div class="image-row">
            <div v-for="url in ((sectionConfig?.[input.name] as string[]) || [])" :key="url" class="image-thumb">
              <img :src="url" alt="" />
              <button type="button" class="image-remove" title="移除这张图" @click="emit('remove-image-from-list', input.name, url)"><AppIcon name="x" /></button>
            </div>
            <label class="btn btn-sm upload-label">
              <AppIcon name="plus" />添加图片
              <input type="file" accept="image/*" class="hidden-file" @change="onFileChange(input.name, $event, true)" />
            </label>
          </div>
        </div>

        <div v-else-if="input.type === 'action'" class="field">
          <span class="field-label">{{ input.label }}</span>
          <div class="action-row">
            <button v-for="val in input.values" :key="val.name" type="button" class="btn" @click="emit('fire-action', input.name, val.name)">{{ val.label }}</button>
          </div>
        </div>
      </div>
    </div>

    <footer v-if="hasNonActionInputs" class="section-foot">
      <span v-if="status === 'saved'" class="sent"><AppIcon name="check" />已发送</span>
      <button type="button" class="btn btn-primary" :disabled="status === 'saving'" @click="emit('save')">
        <AppIcon name="zap" />{{ status === 'saving' ? '正在发送…' : '保存并发送' }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.hud-section { overflow: hidden; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.section-head h2 { font-size: 14px; font-weight: 700; }
.active-toggle { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--text-2); cursor: pointer; }
.section-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 16px; padding: 16px; }
.section-field.wide { grid-column: 1 / -1; }
.checkbox-field { height: 100%; align-items: flex-end; padding-bottom: 7px; }
.field-note { margin-top: 6px; font-size: 12px; color: var(--gold); }
.image-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.image-thumb { position: relative; width: 56px; height: 56px; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-md); background: var(--bg-input); border: 1px solid var(--border-strong); }
.image-thumb img { width: 100%; height: 100%; object-fit: contain; }
.image-remove { position: absolute; inset: 0; display: none; place-items: center; border: none; background: rgba(0, 0, 0, 0.6); color: #ff9d95; }
.image-thumb:hover .image-remove { display: grid; }
.upload-label { cursor: pointer; }
.hidden-file { display: none; }
.action-row { display: flex; flex-wrap: wrap; gap: 8px; }
.section-foot { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 10px 16px; border-top: 1px solid var(--border); background: var(--bg-raised); }
.sent { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: #8fd3ad; }
.sent .icon { width: 13px; height: 13px; }
</style>
