<script setup lang="ts">
// 观战按键：把选手固定到数字键 1–0，再把按键设置发给 CS2
import { watch } from 'vue'
import AppIcon from '../components/ui/AppIcon.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import BaseInput from '../components/base/BaseInput.vue'
import { useSpectator } from '../features/spectator/composables/useSpectator'
import SpectatorInfoModal from '../features/spectator/components/SpectatorInfoModal.vue'
import SpectatorTelnetSettings from '../features/spectator/components/SpectatorTelnetSettings.vue'
import SpectatorSlotGrid from '../features/spectator/components/SpectatorSlotGrid.vue'
import SpectatorLivePlayers from '../features/spectator/components/SpectatorLivePlayers.vue'
import SpectatorCommandPreview from '../features/spectator/components/SpectatorCommandPreview.vue'
import { showToast } from '../composables/useToasts'

const {
  gameState, slots, telnetHost, telnetPort, settingsOpen, showInfo, settingsSaving,
  applying, applyResult, clearing, testing, testResult,
  livePlayers, ctPlayers, tPlayers, allPlayerNames, sideForName,
  preCommand, previewCommand, numericNameWarnings,
  saveSettings, testConnection, applyBinds, clearBinds, quickAssign, clearSlot, fillFromCS2,
  SLOT_KEYS, buildCommand
} = useSpectator()

// 应用 / 清空 / 测试连接的结果：右上角提示（成功会自己消失，失败要手动关）
watch(applyResult, (result) => {
  if (result) showToast(result.message, result.ok ? 'success' : 'error', { key: 'spectator-apply' })
})
watch(testResult, (result) => {
  if (result) showToast(result.message, result.ok ? 'success' : 'error', { key: 'spectator-test' })
})
// 名字以数字开头的选手绑不了数字键（CS2 本身的限制）
watch(
  () => numericNameWarnings.value.join('、'),
  (names) => {
    if (names) showToast(`名字以数字开头的选手无法使用按键绑定（CS2 本身的限制）：${names}`, 'warn', { key: 'spectator-numeric' })
  }
)
</script>

<template>
  <div class="page">
    <SpectatorInfoModal :show="showInfo" @close="showInfo = false" />

    <PageHeader kicker="Observer keys" title="观战按键" description="比赛前给每名选手分一个数字键">
      <button type="button" class="btn btn-ghost" @click="showInfo = true"><AppIcon name="info" />使用说明</button>
      <button type="button" class="btn" :class="{ 'is-open': settingsOpen }" @click="settingsOpen = !settingsOpen"><AppIcon name="terminal" />连接设置</button>
      <button type="button" class="btn" :disabled="clearing || applying" title="清空全部选手位置，并恢复 CS2 默认数字键" @click="clearBinds">
        <AppIcon name="x" />{{ clearing ? '正在清空…' : '全部清空' }}
      </button>
      <button type="button" class="btn btn-primary" :disabled="applying" @click="applyBinds">
        <AppIcon name="zap" />{{ applying ? '正在应用…' : '应用到 CS2' }}
      </button>
    </PageHeader>

    <SpectatorTelnetSettings
      v-if="settingsOpen"
      v-model:host="telnetHost"
      v-model:port="telnetPort"
      :testing="testing"
      :saving="settingsSaving"
      @test="testConnection"
      @save="saveSettings"
    />

    <SpectatorSlotGrid
      :slots="slots"
      :live-players="livePlayers"
      :all-player-names="allPlayerNames"
      :side-for-name="sideForName"
      :slot-keys="SLOT_KEYS"
      :warned-names="numericNameWarnings"
      @clear-slot="clearSlot"
      @fill-from-cs2="fillFromCS2"
    />

    <SpectatorLivePlayers
      :game-state="gameState"
      :live-players="livePlayers"
      :ct-players="ctPlayers"
      :t-players="tPlayers"
      @quick-assign="quickAssign"
    />

    <div class="bottom-row">
      <section class="panel panel-pad pre-command">
        <div class="panel-head"><b>绑定前执行的命令（可选）</b></div>
        <p class="hint">每次切换选手前先执行，例如用 <code>reset_cams</code> 重置 HLAE 镜头。</p>
        <BaseInput v-model="preCommand" placeholder="例如：reset_cams" />
      </section>
      <SpectatorCommandPreview v-if="Object.values(slots).some(Boolean)" :preview-command="previewCommand" :build-command="buildCommand" />
    </div>
  </div>
</template>

<style scoped>
.btn.is-open { border-color: var(--accent); color: var(--accent); }
.bottom-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.pre-command { display: flex; flex-direction: column; gap: 10px; }
code { padding: 1px 5px; border-radius: var(--radius-sm); background: var(--bg-raised); font-family: Consolas, monospace; font-size: 12px; color: var(--text-2); }
</style>
