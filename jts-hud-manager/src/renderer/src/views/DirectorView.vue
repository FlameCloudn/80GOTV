<script setup lang="ts">
// 导播台：左边场景大按钮 + 最近操作；右边网站上传、网站比赛、OBS 地址、全部隐藏
import { computed, ref } from 'vue'
import AppIcon from '../components/ui/AppIcon.vue'
import type { IconName } from '../components/ui/icons'
import SceneTile, { type SceneKind } from '../features/director/components/SceneTile.vue'
import ActivityPanel from '../features/director/components/ActivityPanel.vue'
import WebsitePanel from '../features/director/components/WebsitePanel.vue'
import UploadPanel from '../features/director/components/UploadPanel.vue'
import ObsSourcePanel from '../features/director/components/ObsSourcePanel.vue'
import ShortcutDialog from '../features/director/components/ShortcutDialog.vue'
import { useDirectorActions } from '../features/director/composables/useDirectorActions'
import { useDirectorShortcuts } from '../features/director/composables/useDirectorShortcuts'
import { useDirectorStatus } from '../composables/useDirectorStatus'
import { formatClock } from '../composables/useActivityLog'

type SceneButton = {
  command: string
  shortcut: string
  label: string
  sub: string
  icon: IconName
  kind: SceneKind
  preview: string
  scene?: string
  done: string
}

const status = useDirectorStatus()
const actions = useDirectorActions()
const shortcuts = useDirectorShortcuts()
const shortcutsOpen = ref(false)

const liveScenes: SceneButton[] = [
  { command: 'auto', shortcut: 'auto', label: '自动跟随', sub: '自动识别暂停和中场', icon: 'radio', kind: 'game', preview: '', scene: 'auto', done: '已切换：自动跟随' },
  { command: 'game', shortcut: 'game', label: '切出覆盖层', sub: '只保留比赛 HUD', icon: 'gamepad', kind: 'game', preview: '', scene: 'game', done: '已切换：只保留比赛 HUD' },
  { command: 'pause_current', shortcut: 'pause_tactical', label: '战术暂停', sub: '暂停画面和倒计时', icon: 'pause', kind: 'pause', preview: 'pausePreview=tactical', scene: 'pause_current', done: '已切换：战术暂停' },
  { command: 'pause_technical', shortcut: 'pause_technical', label: '技术暂停', sub: '技术问题处理中', icon: 'alert', kind: 'pause', preview: 'pausePreview=technical', scene: 'pause_technical', done: '已切换：技术暂停' }
]
const keyScenes = computed<SceneButton[]>(() => [
  { command: 'bp', shortcut: 'bp', label: '赛前 BP', sub: '地图选择锁定后展示', icon: 'map', kind: 'bp', preview: 'bpPreview=1', done: '已展示 BP' },
  { command: 'halftime', shortcut: 'halftime', label: '中场', sub: '半场比分与选手数据', icon: 'timer', kind: 'half', preview: 'halftimePreview=1', scene: 'halftime', done: '已切换：中场' },
  { command: 'map_end', shortcut: 'map_end', label: '单图结束', sub: '这张图的结果', icon: 'flag', kind: 'post', preview: 'victoryPreview=1', scene: 'map_end', done: '已切换：单图结束' },
  { command: 'series_end', shortcut: 'series_end', label: status.currentMatch.value ? `${status.currentBo.value} 结束` : '整场结束', sub: '整场比赛总结', icon: 'trophy', kind: 'post', preview: 'seriesPreview=1', scene: 'series_end', done: '已切换：整场结束' }
])

const isOnAir = (button: SceneButton) =>
  Boolean(button.scene && status.director.value.visible && status.director.value.scene === button.scene)
const bpFlash = computed(() => actions.bpFlashUntil.value > status.now.value)
const hidden = computed(() => !status.director.value.visible)
const hidePending = computed(() => hidden.value && status.director.value.hudClients === 0)

const lastConfirmed = computed(() =>
  formatClock(status.integration.value?.lastConfirmedAt || status.integration.value?.lastConnectionTestAt)
)

const openShortcutRecording = (command: string) => void shortcuts.startRecording(command)
const closeShortcuts = () => {
  if (shortcuts.recording.value) shortcuts.cancelRecording()
  shortcutsOpen.value = false
}
</script>

<template>
  <div class="director">
    <section class="deck">
      <div class="deck-head">
        <div><div class="kicker">Scenes</div><h1>场景切换</h1></div>
        <span class="hint">点一下立刻切换，不会自动跳到下一步</span>
        <button type="button" class="btn btn-ghost btn-sm" @click="shortcutsOpen = true"><AppIcon name="keyboard" />快捷键</button>
      </div>

      <div class="group-label">比赛进行中</div>
      <div class="tiles">
        <SceneTile
          v-for="button in liveScenes"
          :key="button.command"
          :label="button.label"
          :sub="button.sub"
          :icon="button.icon"
          :kind="button.kind"
          :shortcut="shortcuts.bindings.value[button.shortcut]"
          :active="isOnAir(button)"
          :disabled="actions.commandBusy.value"
          @run="actions.run(button.command, button.done)"
          @preview="actions.openPreview(button.preview)"
        />
      </div>

      <div class="group-label">节点画面</div>
      <div class="tiles">
        <SceneTile
          v-for="button in keyScenes"
          :key="button.command"
          :label="button.label"
          :sub="button.sub"
          :icon="button.icon"
          :kind="button.kind"
          :shortcut="shortcuts.bindings.value[button.shortcut]"
          :active="isOnAir(button)"
          :flash="button.command === 'bp' && bpFlash"
          :disabled="actions.commandBusy.value"
          @run="actions.run(button.command, button.done)"
          @preview="actions.openPreview(button.preview)"
        />
      </div>

      <ActivityPanel class="activity" />
    </section>

    <aside class="dock">
      <UploadPanel :integration="status.integration.value" :cs2-fresh="status.cs2Fresh.value" @toggle="actions.toggleForwardLive" />
      <WebsitePanel
        :matches="actions.websiteMatches.value"
        :selected="actions.selectedWebsiteMatch.value"
        :list-busy="actions.listBusy.value"
        :sync-busy="actions.syncBusy.value"
        :check-busy="actions.connectionBusy.value"
        :can-check="Boolean(status.selectedMatch.value)"
        :last-confirmed="lastConfirmed"
        :confirmed-fresh="status.uploadConfirmed.value"
        @choose="actions.chooseWebsiteMatch"
        @reload="actions.loadWebsiteMatches"
        @sync="actions.syncWebsiteMatch"
        @check="actions.testConnection"
      />
      <ObsSourcePanel :url="actions.browserSourceUrl.value" @copy="actions.copyBrowserSource" @preview="actions.openPreview()" />
      <button
        type="button"
        class="panic"
        :class="{ engaged: hidden }"
        :disabled="actions.commandBusy.value"
        title="紧急情况：立刻把 HUD 全部隐藏，观众只看到纯游戏画面"
        @click="actions.run('hide_all', 'HUD 已全部隐藏')"
      >
        <AppIcon name="eyeOff" />
        <span class="panic-text">
          <b>{{ hidden ? hidePending ? '已保存隐藏目标' : '隐藏指令已发送' : '全部隐藏' }}</b>
          <small>{{ hidden ? hidePending ? 'HUD 连接后会应用' : `${status.director.value.hudClients} 个 HUD 连接；未确认 OBS 已显示` : '紧急切回纯游戏画面' }}</small>
        </span>
        <span v-if="shortcuts.bindings.value.hide_all" class="kbd">{{ shortcuts.bindings.value.hide_all }}</span>
      </button>
    </aside>

    <ShortcutDialog
      v-if="shortcutsOpen"
      :bindings="shortcuts.bindings.value"
      :recording="shortcuts.recording.value"
      @record="openShortcutRecording"
      @clear="shortcuts.clearShortcut"
      @close="closeShortcuts"
    />
  </div>
</template>

<style scoped>
.director { height: 100%; display: grid; grid-template-columns: minmax(0, 1fr) 312px; gap: 16px; padding: 14px 20px; overflow: hidden; }
.deck { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.deck-head { display: flex; align-items: center; gap: 12px; }
.deck-head h1 { font-size: 15px; font-weight: 700; line-height: 1.3; }
.deck-head .hint { margin-left: auto; }
.group-label { margin: 12px 0 8px; font-size: 12px; font-weight: 600; color: var(--text-3); }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.activity { margin-top: 14px; flex: 1; }
.dock { display: flex; flex-direction: column; gap: 12px; min-height: 0; overflow-y: auto; }
.panic { margin-top: auto; flex: none; height: 62px; display: flex; align-items: center; gap: 12px; padding: 0 14px; border-radius: var(--radius-lg); border: 1px solid rgba(239, 91, 82, 0.6); background: linear-gradient(180deg, rgba(239, 91, 82, 0.24), rgba(239, 91, 82, 0.12)); color: #ffd2ce; text-align: left; transition: background-color 0.12s; }
.panic:hover:not(:disabled) { background: linear-gradient(180deg, rgba(239, 91, 82, 0.34), rgba(239, 91, 82, 0.18)); }
.panic .icon { width: 22px; height: 22px; color: var(--live); }
.panic-text b { display: block; font-size: 16px; color: #fff; }
.panic-text small { display: block; font-size: 12px; color: #f0a39c; }
.panic .kbd { margin-left: auto; background: rgba(0, 0, 0, 0.25); border-color: rgba(239, 91, 82, 0.5); color: #ffd2ce; }
.panic.engaged { border: 2px solid var(--live); background: rgba(239, 91, 82, 0.3); }
</style>
