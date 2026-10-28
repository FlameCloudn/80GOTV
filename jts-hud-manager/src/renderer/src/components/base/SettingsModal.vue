<script setup lang="ts">
// 设置：比赛自动处理、80GOTV 网站连接、CS2 的 GSI 配置。从左下角“设置”打开，贴着左侧图标栏。
import { ref, watch } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import { useSettings } from '../../features/settings/composables/useSettings'
import { showToast } from '../../composables/useToasts'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { settings, isLoading, isSaving, fetchSettings, saveSettings } = useSettings()

type Cs2PathResult = { ok: boolean; paths: string[]; selected: string; message: string }

const steamPath = ref('')
const detectedSteamPaths = ref<string[]>([])
const pathDetectionMessage = ref('')
const isDetectingCs2 = ref(false)
const isInstallingGsi = ref(false)

watch(() => props.open, async (open) => {
  if (!open) return
  await fetchSettings()
  if (!steamPath.value) await detectCs2Paths()
})

const toggleAutoSwitch = async () => {
  const next = !settings.value.autoSwitchSides
  if (!(await saveSettings({ autoSwitchSides: next }))) showToast('半场自动换边没有保存成功', 'error', { key: 'settings' })
}

const saveWebsiteConnection = async () => {
  const ok = await saveSettings({ websiteUrl: settings.value.websiteUrl, websiteGsiToken: settings.value.websiteGsiToken })
  if (ok) showToast('网站连接设置已保存', 'success', { key: 'settings' })
  else showToast('网站连接设置没有保存成功', 'error', { key: 'settings' })
}

const openLogFolder = () => window.electron.ipcRenderer.invoke('open-log-folder')

const detectCs2Paths = async () => {
  isDetectingCs2.value = true
  pathDetectionMessage.value = ''
  try {
    const result = (await window.electron.ipcRenderer.invoke('detect-cs2-paths')) as Cs2PathResult
    detectedSteamPaths.value = result.paths || []
    if (result.selected) steamPath.value = result.selected
    pathDetectionMessage.value = result.message
  } catch (error) {
    pathDetectionMessage.value = error instanceof Error ? error.message : '自动查找失败，请手动选择。'
  } finally {
    isDetectingCs2.value = false
  }
}

const browseSteamFolder = async () => {
  const selected = await window.electron.ipcRenderer.invoke('select-folder', steamPath.value)
  if (selected) steamPath.value = selected
}

// 安装结果：成功会自己消失，失败要手动关
const installGsiCfg = async () => {
  isInstallingGsi.value = true
  try {
    const result = (await window.electron.ipcRenderer.invoke('install-gsi-cfg', steamPath.value)) as { ok: boolean; message: string }
    showToast(result.message, result.ok ? 'success' : 'error', { key: 'gsi-install', title: result.ok ? 'GSI 配置已安装' : 'GSI 配置没装上' })
  } catch (error) {
    showToast(error instanceof Error ? error.message : String(error), 'error', { key: 'gsi-install' })
  } finally {
    isInstallingGsi.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="settings-layer" @mousedown.self="emit('close')">
        <div class="dialog settings" role="dialog" aria-label="设置">
          <div class="dialog-head">
            <AppIcon name="sliders" />
            <h2>设置</h2>
            <button type="button" class="icon-btn dialog-close" title="关闭" @click="emit('close')"><AppIcon name="x" /></button>
          </div>

          <div v-if="isLoading" class="dialog-body loading">正在加载…</div>
          <div v-else class="dialog-body settings-body">
            <section class="block">
              <div class="kicker">比赛自动处理</div>
              <div class="setting-row">
                <div>
                  <b>半场自动换边</b>
                  <p class="hint">中场后只换两队的阵营颜色，队伍位置不变</p>
                </div>
                <button type="button" class="switch" :class="{ on: settings.autoSwitchSides }" role="switch" :aria-checked="settings.autoSwitchSides" :disabled="isSaving" @click="toggleAutoSwitch" />
              </div>
            </section>

            <section class="block">
              <div class="kicker">80GOTV 网站连接</div>
              <div class="field">
                <label for="settings-website-url">网站地址</label>
                <input id="settings-website-url" v-model="settings.websiteUrl" class="input" type="url" placeholder="https://80gotv.cn" />
              </div>
              <div class="field">
                <label for="settings-gsi-token">GSI 密钥</label>
                <input id="settings-gsi-token" v-model="settings.websiteGsiToken" class="input" type="password" autocomplete="off" placeholder="和网站服务器的 GSI_TOKEN 一样" />
              </div>
              <button type="button" class="btn" :disabled="isSaving" @click="saveWebsiteConnection">{{ isSaving ? '保存中…' : '保存网站连接设置' }}</button>
              <p class="hint">选比赛、检查连接、同步资料和实时上传都在「导播台」里做，避免两处设置不一致。</p>
              <div class="setting-row log-row">
                <p class="hint">连接或画面出问题时，把日志文件夹发给维护人员。</p>
                <button type="button" class="btn btn-sm" @click="openLogFolder"><AppIcon name="folder" />打开日志文件夹</button>
              </div>
            </section>

            <section class="block">
              <div class="kicker">CS2 连接</div>
              <div>
                <b>安装 GSI 配置</b>
                <p class="hint">程序会先自动找 CS2。换电脑或游戏装在别的硬盘时，也可以手动选 SteamLibrary 文件夹。</p>
              </div>
              <div class="detect-row">
                <p class="detect-text">{{ pathDetectionMessage || '还没检查这台电脑上的 CS2 安装位置。' }}</p>
                <button type="button" class="btn btn-sm" :disabled="isDetectingCs2" @click="detectCs2Paths"><AppIcon name="search" />{{ isDetectingCs2 ? '查找中…' : '自动查找' }}</button>
              </div>
              <select v-if="detectedSteamPaths.length > 1" v-model="steamPath" class="select" aria-label="选择 Steam 位置">
                <option v-for="candidate in detectedSteamPaths" :key="candidate" :value="candidate">{{ candidate }}</option>
              </select>
              <div class="path-row">
                <input v-model="steamPath" class="input" type="text" placeholder="C:\Program Files (x86)\Steam" aria-label="Steam 文件夹" />
                <button type="button" class="btn" @click="browseSteamFolder"><AppIcon name="folder" />浏览</button>
              </div>
              <button type="button" class="btn btn-primary" :disabled="isInstallingGsi || !steamPath" @click="installGsiCfg">
                {{ isInstallingGsi ? '正在安装…' : '安装 GSI 配置' }}
              </button>
            </section>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.settings-layer { position: fixed; inset: 0; z-index: 300; background: rgba(5, 6, 8, 0.5); }
.settings { position: absolute; left: 88px; bottom: 40px; width: 520px; max-height: calc(100vh - 56px); }
.loading { padding: 24px; text-align: center; color: var(--text-3); }
.settings-body { display: flex; flex-direction: column; gap: 0; padding: 0; }
.block { display: flex; flex-direction: column; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--border); }
.block:last-child { border-bottom: none; }
.block b { font-size: 13px; }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.log-row { padding-top: 10px; border-top: 1px solid var(--border); }
.detect-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 10px; border-radius: var(--radius-md); background: var(--bg-raised); border: 1px solid var(--border); }
.detect-text { min-width: 0; font-size: 12px; color: var(--text-2); overflow-wrap: anywhere; }
.path-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
