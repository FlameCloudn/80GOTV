<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import type { SelectOption } from '@renderer/components/base/BaseSelect.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';
import BaseSelect from '@renderer/components/base/BaseSelect.vue';
import { useMatches } from '../features/matches/composables/useMatches';
import { useTeams } from '../features/teams/composables/useTeams';
import { API_URL } from '../index';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import BaseCheckbox from '@renderer/components/base/BaseCheckbox.vue';

const router = useRouter();
const route = useRoute();

const { saveMatch } = useMatches();
const { teams, fetchTeams } = useTeams();

const isEditing = computed(() => !!route.params.id);
const isSaving = ref(false);

const CS2_MAPS = [
  'de_ancient', 'de_anubis', 'de_dust2', 'de_inferno',
  'de_mirage', 'de_nuke', 'de_overpass', 'de_train', 'de_vertigo', 'de_cache'
];
const VETO_TYPES = ['ban', 'pick', 'decider'] as const;
const SIDES = ['CT', 'T', 'NO'] as const;
const SLOT_COUNT = 9;

const makeEmptySlot = () => null as null | any;

const getEmptyForm = () => ({
  current: false,
  matchType: 'bo3',
  left:  { id: '' as string, wins: 0 },
  right: { id: '' as string, wins: 0 },
  vetos: Array.from({ length: SLOT_COUNT }, makeEmptySlot) as (any | null)[]
});

const form = ref(getEmptyForm());

// Convert data to SelectOption[] format
const mapOptions = computed((): SelectOption[] =>
  CS2_MAPS.map(m => ({ value: m, label: m }))
);

const vetoTypeOptions = computed((): SelectOption[] =>
  VETO_TYPES.map(t => ({
    value: t,
    label: t === 'ban' ? '禁用地图' : t === 'pick' ? '选择地图' : '决胜地图'
  }))
);

const availableTeamsForLeft = computed((): SelectOption[] =>
  teams.value.filter(t => t._id !== form.value.right.id).map(t => ({ value: t._id, label: t.name }))
);

const availableTeamsForRight = computed((): SelectOption[] =>
  teams.value.filter(t => t._id !== form.value.left.id).map(t => ({ value: t._id, label: t.name }))
);

const vetoTeamsOptions = computed((): SelectOption[] => [
  form.value.left?.id ? { value: form.value.left.id, label: getTeamName(form.value.left.id) } : { value: '', label: '—' },
  form.value.right?.id ? { value: form.value.right.id, label: getTeamName(form.value.right.id) } : { value: '', label: '—' },
  { value: '', label: '—' }
].filter((o, i, arr) => arr.findIndex(a => a.value === o.value) === i));

const vetoWinnerOptions = computed((): SelectOption[] => [
  { value: '', label: '无' },
  ...(form.value.left?.id ? [{ value: form.value.left.id, label: getTeamName(form.value.left.id) }] : []),
  ...(form.value.right?.id ? [{ value: form.value.right.id, label: getTeamName(form.value.right.id) }] : [])
]);

// Load match data if editing
onMounted(async () => {
  await fetchTeams();
  if (isEditing.value) {
    try {
      const res = await fetch(`${API_URL}/match/${route.params.id}`);
      if (res.ok) {
        const data = await res.json();
        // Pad the vetos array to 9 slots
        const padded = Array.from({ length: SLOT_COUNT }, (_, i) => data.vetos[i] ?? null);
        form.value = { ...data, vetos: padded };
      }
    } catch (e) {
      console.error('Failed to load match', e);
    }
  }
});

const bothTeamsSelected = computed(() =>
  !!form.value.left.id && !!form.value.right.id && form.value.left.id !== form.value.right.id
);

const getTeamName = (id: string | null) => {
  if (!id) return '待定';
  return teams.value.find(t => t._id === id)?.name ?? '未知';
};

const getVetoTypeLabel = (type: string) =>
  type === 'ban' ? '禁用' : type === 'pick' ? '选择' : '决胜';

const filledCount = computed(() => form.value.vetos.filter(Boolean).length);

// --- VETO MODAL ---
const isVetoModalOpen = ref(false);
const editingSlot = ref<number | null>(null);
const showResultOverride = ref(false);

const getDefaultVetoForm = () => ({
  teamId: '' as string,
  mapName: 'de_mirage',
  side: 'NO' as string,
  type: 'pick' as string,
  reverseSide: false,
  openingCtTeamId: undefined as string | undefined,
  sideSource: 'unknown' as 'website_bp' | 'tgpro_stable_gsi' | 'legacy_manual' | 'unknown',
  mapEnd: false,
  winner: '' as string,
  score: {} as Record<string, number>
});

const vetoForm = ref(getDefaultVetoForm());
const vetoSideLocked = computed(() =>
  Boolean(vetoForm.value.openingCtTeamId) ||
  vetoForm.value.sideSource === 'website_bp' ||
  vetoForm.value.sideSource === 'tgpro_stable_gsi'
);

// When type is set to 'decider', clear the team selection
watch(() => vetoForm.value.type, (newType) => {
  if (newType === 'decider') {
    vetoForm.value.teamId = '';
  }
});

const openVetoModal = (index: number) => {
  if (!bothTeamsSelected.value) return;
  editingSlot.value = index;
  const existing = form.value.vetos[index];
  vetoForm.value = existing
    ? { ...getDefaultVetoForm(), ...existing, score: { ...(existing.score ?? {}) } }
    : { ...getDefaultVetoForm(), teamId: form.value.left.id ?? '' };
  showResultOverride.value = false;
  isVetoModalOpen.value = true;
};

const clearSlot = (index: number) => {
  form.value.vetos[index] = null;
};

const saveVetoModal = () => {
  if (editingSlot.value === null) return;
  form.value.vetos[editingSlot.value] = { ...vetoForm.value };
  isVetoModalOpen.value = false;
  editingSlot.value = null;
};

const getScore = (score: Record<string, number>, teamId: string) => score?.[teamId] ?? 0;
const setScore = (teamId: string, val: string) => {
  if (!vetoForm.value.score) vetoForm.value.score = {};
  vetoForm.value.score[teamId] = Number(val);
};

const handleSave = async () => {
  isSaving.value = true;
  try {
    // Strip null slots before saving
    const payload = { ...form.value, vetos: form.value.vetos.filter(Boolean) };
    await saveMatch(payload, isEditing.value ? String(route.params.id) : null);
    router.push('/matches');
  } catch (e) {
    console.error(e);
  } finally {
    isSaving.value = false;
  }
};

const vetoTypeColor: Record<string, string> = {
  ban:     'text-red-400 bg-red-900/30 border-red-800/50',
  pick:    'text-emerald-400 bg-emerald-900/30 border-emerald-800/50',
  decider: 'text-yellow-400 bg-yellow-900/30 border-yellow-800/50',
};
</script>

<template>
  <div class="flex flex-col h-full bg-surface text-zinc-200">

    <!-- Header bar -->
    <div class="flex items-center justify-between p-6 shrink-0">
      <div class="flex items-center gap-3">
        <button @click="router.push('/matches')" class="text-zinc-500 hover:text-zinc-200 transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div>
          <h1 class="text-2xl font-bold text-text-main tracking-tight">{{ isEditing ? '编辑比赛' : '创建比赛' }}</h1>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <BaseButton variant="danger" @click="router.push('/matches')">
          取消
        </BaseButton>
        <BaseButton
          @click="handleSave"
          :disabled="isSaving"
          :variant="isSaving ? 'secondary' : 'primary'"
        >
          {{ isSaving ? '正在保存...' : isEditing ? '保存更改' : '创建比赛' }}
        </BaseButton>
      </div>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-y-auto p-6">
      <div class="max-w-4xl mx-auto space-y-6">

        <!-- Match type + current toggle -->
        <div class="bg-zinc-800 border border-border rounded-xl p-5 flex items-center gap-6">
          <div class="flex-1">
            <label class="block text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-2">比赛赛制</label>
            <div class="flex gap-2">
              <BaseButton
                v-for="type in ['bo1','bo2','bo3','bo5']"
                :key="type"
                @click="form.matchType = type"
                :variant="form.matchType === type ? 'primary' : 'secondary'"
                :class="form.matchType === type ? '' : 'bg-zinc-900!'"
              >
                {{ type }}
              </BaseButton>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <label class="text-sm text-zinc-400">设为当前比赛</label>
            <button
              type="button"
              @click="form.current = !form.current"
              class="relative w-11 h-6 rounded-full transition-colors"
              :class="form.current ? 'bg-primary' : 'bg-zinc-700'"
            >
              <span class="absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform" :class="form.current ? 'translate-x-5' : 'translate-x-0'" />
            </button>
          </div>
        </div>

        <!-- Teams -->
        <div class="grid grid-cols-2 gap-4">
          <!-- Left -->
          <div class="bg-zinc-800 border border-border rounded-xl p-5">
            <label class="block text-xs font-bold uppercase tracking-wider text-blue-400 mb-3 pb-2 border-b border-border">左侧战队</label>
            <div class="space-y-3">
              <BaseSelect
                v-model="form.left.id"
                placeholder="搜索战队..."
                :options="availableTeamsForLeft"
                clearable
                searchable
                size="md"
              />
              <div>
                <BaseInput
                  v-model.number="form.left.wins"
                  type="number"
                  label="初始大比分"
                  size="md"
                />
              </div>
            </div>
          </div>
          <!-- Right -->
          <div class="bg-zinc-800 border border-border rounded-xl p-5">
            <label class="block text-xs font-bold uppercase tracking-wider text-amber-400 mb-3 pb-2 border-b border-border">右侧战队</label>
            <div class="space-y-3">
              <BaseSelect
                v-model="form.right.id"
                placeholder="搜索战队..."
                :options="availableTeamsForRight"
                clearable
                searchable
                size="md"
              />
              <div>
                <BaseInput
                  v-model.number="form.right.wins"
                  type="number"
                  label="初始大比分"
                  size="md"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Veto section -->
        <div class="bg-zinc-800 border border-border rounded-xl p-5">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-sm font-bold text-text-main">地图选择顺序</h2>
              <p class="text-xs text-zinc-500 mt-0.5">
                <template v-if="!bothTeamsSelected">选择两支战队后才能设置地图。</template>
                <template v-else>已设置 {{ filledCount }} / {{ SLOT_COUNT }} 项，点击任意一项进行编辑。</template>
              </p>
            </div>
          </div>

          <!-- Locked state -->
          <div v-if="!bothTeamsSelected" class="flex flex-col items-center justify-center py-10 border border-dashed border-border rounded-lg text-zinc-600 gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            <span class="text-sm">请先在上方选择两支战队</span>
          </div>

          <!-- 9 Slots grid -->
          <div v-else class="space-y-2">
            <div
              v-for="(veto, i) in form.vetos"
              :key="i"
              class="flex items-center gap-3 rounded-lg border px-4 py-3 transition-colors"
              :class="veto
                ? 'bg-surface border-border cursor-pointer hover:border-zinc-500'
                : 'bg-surface/40 border-border border-dashed'"
            >
              <!-- Slot number -->
              <span class="text-xs font-bold text-zinc-600 w-5 shrink-0 text-center">{{ i + 1 }}</span>

              <!-- Empty slot -->
              <template v-if="!veto">
                <span class="text-xs text-zinc-600 flex-1">空项目</span>
                <BaseButton
                  type="button"
                  @click="openVetoModal(i)"
                  size="sm"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
                  设置
                </BaseButton>
              </template>

              <!-- Filled slot -->
              <template v-else>
                <!-- Type badge -->
                <span :class="vetoTypeColor[veto.type]" class="text-[9px] font-bold uppercase tracking-wider px-2 py-1 rounded border shrink-0">
                  {{ getVetoTypeLabel(veto.type) }}
                </span>

                <!-- Map name -->
                <span class="text-sm font-semibold text-text-main flex-1 truncate">{{ veto.mapName }}</span>

                <!-- Team + side -->
                <div class="flex items-center gap-2 shrink-0">
                  <span v-if="veto.type === 'decider'" class="text-xs text-zinc-400">决胜地图</span>
                  <span v-else class="text-xs text-zinc-400">{{ getTeamName(veto.teamId) }}</span>
                  <span v-if="veto.side !== 'NO'" class="text-xs font-bold uppercase px-1.5 py-0.5 rounded border"
                    :class="veto.side === 'CT' ? 'text-blue-400 border-blue-800/50 bg-blue-900/20' : 'text-amber-400 border-amber-800/50 bg-amber-900/20'">
                    {{ veto.side }}
                  </span>
                  <span v-if="veto.mapEnd" class="text-xs font-bold uppercase text-emerald-400 bg-emerald-900/20 border border-emerald-800/50 px-1.5 py-0.5 rounded">已结束</span>
                </div>

                <!-- Actions -->
                <div class="flex items-center gap-1 shrink-0">
                  <button type="button" @click="openVetoModal(i)" title="编辑" class="p-1.5 rounded text-zinc-500 hover:text-blue-400 hover:bg-primary/10 transition-colors">
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                  </button>
                  <button type="button" @click="clearSlot(i)" title="清空这一项" class="p-1.5 rounded text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors">
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                  </button>
                </div>
              </template>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>

  <!-- Veto Edit Modal -->
  <div v-if="isVetoModalOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
    <div class="bg-surface rounded-xl border border-border w-full max-w-md shadow-2xl flex flex-col overflow-hidden">

      <!-- Header -->
      <div class="p-5 border-b border-border flex justify-between items-center">
        <h2 class="text-base font-bold text-text-main">设置第 {{ editingSlot !== null ? editingSlot + 1 : '' }} 项</h2>
        <button @click="isVetoModalOpen = false" class="text-zinc-400 hover:text-text-main transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Body -->
      <div class="p-5 space-y-4 overflow-y-auto">

        <!-- Map -->
        <BaseSelect
          v-model="vetoForm.mapName"
          label="地图"
          :options="mapOptions"
          size="md"
        />

        <!-- Team + Type -->
        <div class="grid grid-cols-2 gap-3">
          <BaseSelect
            v-model="vetoForm.teamId"
            label="战队"
            :options="vetoTeamsOptions"
            :disabled="vetoForm.type === 'decider'"
            size="md"
          />
          <BaseSelect
            v-model="vetoForm.type"
            label="选择类型"
            :options="vetoTypeOptions"
            size="md"
          />
        </div>

        <!-- Side -->
        <div>
          <label class="block text-xs font-bold uppercase tracking-wider text-zinc-400 mb-1.5">起始阵营</label>
          <div class="flex gap-2">
            <button
              v-for="s in SIDES" :key="s" type="button"
              @click="vetoForm.side = s"
              :class="vetoForm.side === s
                ? s === 'CT' ? 'bg-blue-600 text-text-main' : s === 'T' ? 'bg-amber-500 text-text-main' : 'bg-zinc-600 text-text-main'
                : 'bg-surface text-zinc-400 hover:bg-surface-hover'"
              class="flex-1 py-2 rounded-lg border border-border text-xs font-bold uppercase transition-colors hover:cursor-pointer"
            >{{ s }}</button>
          </div>
        </div>

        <!-- Result override toggle -->
        <button type="button" @click="showResultOverride = !showResultOverride" class="flex items-center gap-2 w-full group">
          <div class="flex-1 border-t border-border/50"></div>
          <span class="text-xs font-bold uppercase tracking-wider text-amber-400 group-hover:text-amber-300 transition-colors shrink-0">手动填写结果（可选）</span>
          <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3 text-amber-400 transition-transform shrink-0" :class="{ 'rotate-180': showResultOverride }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
          <div class="flex-1 border-t border-border/50"></div>
        </button>

        <template v-if="showResultOverride">

        <!-- Winner -->
        <BaseSelect
          v-model="vetoForm.winner"
          label="获胜战队"
          :options="vetoWinnerOptions"
          size="md"
        />

        <!-- Scores -->
        <div class="grid grid-cols-2 gap-3">
          <BaseInput
            type="number"
            :model-value="getScore(vetoForm.score, form.left.id!)"
            @update:model-value="e => setScore(form.left.id!, String(e))"
            :label="`${getTeamName(form.left.id)} 得分`"
            placeholder="0"
            size="md"
          />
          <BaseInput
            type="number"
            :model-value="getScore(vetoForm.score, form.right.id!)"
            @update:model-value="e => setScore(form.right.id!, String(e))"
            :label="`${getTeamName(form.right.id)} 得分`"
            placeholder="0"
            size="md"
          />
        </div>

        <!-- Flags -->
        <div class="flex items-center gap-6">
          <BaseCheckbox v-model="vetoForm.reverseSide" label="交换阵营" size="md" class="text-primary" :disabled="vetoSideLocked" />
          <BaseCheckbox v-model="vetoForm.mapEnd" label="地图已结束" size="md" class="text-emerald-500" />
        </div>

        </template>
      </div>

      <!-- Footer -->
      <div class="p-5 border-t border-border flex gap-3">
        <BaseButton class="flex-1 justify-center" @click="isVetoModalOpen = false" variant="secondary">取消</BaseButton>
        <BaseButton class="flex-1 justify-center" @click="saveVetoModal" variant="primary">保存这一项</BaseButton>
      </div>
    </div>
  </div>
</template>
