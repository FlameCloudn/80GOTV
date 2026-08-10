<script setup lang="ts">
import { ref, watch } from 'vue';
import { useSettings } from '../../features/settings/composables/useSettings';
import BaseButton from './BaseButton.vue';
import BaseCheckbox from './BaseCheckbox.vue';

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: 'close'): void }>();

const { settings, isLoading, isSaving, fetchSettings, saveSettings } = useSettings();

type Cs2PathResult = {
  ok: boolean;
  paths: string[];
  selected: string;
  message: string;
};

watch(() => props.open, async (val) => {
  if (val) {
    await fetchSettings();
    if (!steamPath.value) await detectCs2Paths();
  }
});

const saveAutoSwitch = (value: boolean) => saveSettings({ autoSwitchSides: value });
const saveWebsiteConnection = () => saveSettings({
  websiteUrl: settings.value.websiteUrl,
  websiteGsiToken: settings.value.websiteGsiToken
});

const openLogFolder = async () => {
  await window.electron.ipcRenderer.invoke('open-log-folder');
};

// --- GSI Config Installation ---
const steamPath = ref('');
const detectedSteamPaths = ref<string[]>([]);
const pathDetectionMessage = ref('');
const isDetectingCs2 = ref(false);
const gsiStatus = ref<{ ok: boolean; message: string } | null>(null);
const isInstallingGsi = ref(false);

const detectCs2Paths = async () => {
  isDetectingCs2.value = true;
  pathDetectionMessage.value = '';
  try {
    const result = await window.electron.ipcRenderer.invoke('detect-cs2-paths') as Cs2PathResult;
    detectedSteamPaths.value = result.paths || [];
    if (result.selected) steamPath.value = result.selected;
    pathDetectionMessage.value = result.message;
  } catch (error) {
    pathDetectionMessage.value = error instanceof Error ? error.message : '自动查找失败，请手动选择。';
  } finally {
    isDetectingCs2.value = false;
  }
};

const browseSteamFolder = async () => {
  const selected = await window.electron.ipcRenderer.invoke('select-folder', steamPath.value);
  if (selected) {
    steamPath.value = selected;
    gsiStatus.value = null;
  }
};

const installGsiCfg = async () => {
  isInstallingGsi.value = true;
  gsiStatus.value = null;
  try {
    gsiStatus.value = await window.electron.ipcRenderer.invoke('install-gsi-cfg', steamPath.value);
  } finally {
    isInstallingGsi.value = false;
  }
};
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-end justify-start"
        @click.self="emit('close')"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/50" @click="emit('close')" />

        <!-- Panel — anchored to bottom-left near the sidebar -->
        <div class="relative z-10 ml-4 mb-16 w-[520px] max-h-[calc(100vh-6rem)] overflow-y-auto bg-surface border border-zinc-700 rounded-xl shadow-2xl p-5 flex flex-col gap-5">
          
          <div class="flex items-center justify-between">
            <h2 class="text-text-main font-bold text-base">设置</h2>
            <BaseButton @click="emit('close')" variant="ghost" size="sm">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </BaseButton>
          </div>

          <div v-if="isLoading" class="text-zinc-400 text-sm text-center py-4">正在加载...</div>

          <template v-else>
            <!-- Section: Match -->
            <div>
              <p class="text-xs font-semibold text-zinc-500 mb-3">比赛自动处理</p>

              <!-- Auto Switch Sides -->
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-zinc-200">半场自动换边</p>
                  <p class="text-xs text-zinc-500 mt-0.5">中场后只切换两队阵营颜色，队伍位置保持不变</p>
                </div>
                <BaseCheckbox v-model="settings.autoSwitchSides" @update:model-value="saveAutoSwitch" :disabled="isSaving" size="md" class="text-primary" />
              </div>
            </div>

            <div class="border-t border-border pt-4">
              <p class="text-xs font-semibold text-zinc-500 mb-3">80GOTV 网站连接</p>
              <div class="flex flex-col gap-3">
                <label class="text-xs text-zinc-400">
                  网站地址
                  <input
                    v-model="settings.websiteUrl"
                    type="url"
                    placeholder="https://80gotv.cn"
                    class="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-primary"
                  />
                </label>

                <label class="text-xs text-zinc-400">
                  GSI 密钥
                  <input
                    v-model="settings.websiteGsiToken"
                    type="password"
                    placeholder="与网站服务器的 GSI_TOKEN 相同"
                    autocomplete="off"
                    class="mt-1 w-full bg-zinc-800 border border-zinc-700 text-zinc-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-primary"
                  />
                </label>

                <BaseButton @click="saveWebsiteConnection" :disabled="isSaving" variant="secondary" class="justify-center">
                  {{ isSaving ? '保存中...' : '保存网站连接设置' }}
                </BaseButton>

                <p class="text-xs text-zinc-500">比赛选择、连接检查、资料同步和实时上传统一在“导播台”完成，避免两处设置不一致。</p>

                <div class="flex items-center justify-between border-t border-zinc-700 pt-3">
                  <p class="text-xs text-zinc-500">连接或画面异常时，把日志文件夹发给维护人员。</p>
                  <BaseButton @click="openLogFolder" variant="secondary" size="sm" class="shrink-0">
                    打开日志文件夹
                  </BaseButton>
                </div>
              </div>
            </div>

            <!-- Section: CS2 Integration -->
            <div class="border-t border-border pt-4">
              <p class="text-xs font-semibold text-zinc-500 mb-3">CS2 连接</p>

              <div class="flex flex-col gap-2">
                <p class="text-sm font-medium text-zinc-200">安装 GSI 配置</p>
                <p class="text-xs text-zinc-500">程序会先自动寻找 CS2。换电脑或游戏装在其他硬盘时，也可以手动选择 SteamLibrary 文件夹。</p>

                <div class="flex items-center justify-between gap-3 rounded-lg border border-zinc-700 bg-zinc-800/60 px-3 py-2">
                  <p class="min-w-0 text-xs text-zinc-400 break-words">
                    {{ pathDetectionMessage || '尚未检查这台电脑上的 CS2 安装位置。' }}
                  </p>
                  <BaseButton @click="detectCs2Paths" :disabled="isDetectingCs2" variant="secondary" size="sm" class="shrink-0">
                    {{ isDetectingCs2 ? '查找中...' : '自动查找' }}
                  </BaseButton>
                </div>

                <select
                  v-if="detectedSteamPaths.length > 1"
                  v-model="steamPath"
                  class="w-full bg-zinc-800 border border-zinc-700 text-zinc-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-primary"
                >
                  <option v-for="candidate in detectedSteamPaths" :key="candidate" :value="candidate">
                    {{ candidate }}
                  </option>
                </select>

                <!-- Path selector -->
                <div class="flex gap-2 mt-1">
                  <input
                    v-model="steamPath"
                    type="text"
                    placeholder="C:\Program Files (x86)\Steam"
                    class="flex-1 min-w-0 bg-zinc-800 border border-zinc-700 text-zinc-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-primary"
                  />
                  <BaseButton
                    @click="browseSteamFolder"
                    variant="secondary"
                    size="sm"
                  >
                    浏览
                  </BaseButton>
                </div>

                <BaseButton
                  @click="installGsiCfg"
                  :disabled="isInstallingGsi || !steamPath"
                  variant="primary"
                  class="flex-1 justify-center"
                >
                  {{ isInstallingGsi ? '正在安装...' : '安装 GSI 配置' }}
                </BaseButton>

                <!-- Status feedback -->
                <div
                  v-if="gsiStatus"
                  class="text-xs rounded-lg px-3 py-2 whitespace-pre-wrap"
                  :class="gsiStatus.ok ? 'bg-emerald-900/40 text-emerald-400 border border-emerald-800/50' : 'bg-red-900/40 text-red-400 border border-red-800/50'"
                >
                  {{ gsiStatus.message }}
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
