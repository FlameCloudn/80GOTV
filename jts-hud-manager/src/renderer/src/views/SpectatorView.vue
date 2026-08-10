<script setup lang="ts">
import { useSpectator } from '../features/spectator/composables/useSpectator';
import SpectatorInfoModal from '../features/spectator/components/SpectatorInfoModal.vue';
import SpectatorTelnetSettings from '../features/spectator/components/SpectatorTelnetSettings.vue';
import SpectatorSlotGrid from '../features/spectator/components/SpectatorSlotGrid.vue';
import SpectatorLivePlayers from '../features/spectator/components/SpectatorLivePlayers.vue';
import SpectatorCommandPreview from '../features/spectator/components/SpectatorCommandPreview.vue';
import WarningIcon from '@renderer/assets/icons/WarningIcon.vue';
import InfoIcon from '@renderer/assets/icons/InfoIcon.vue';
import SettingsIcon from '@renderer/assets/icons/SettingsIcon.vue';
import CloseIcon from '@renderer/assets/icons/CloseIcon.vue';
import RefreshIcon from '@renderer/assets/icons/RefreshIcon.vue';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import BaseBadge from '@renderer/components/base/BaseBadge.vue';
import BaseInput from '@renderer/components/base/BaseInput.vue';

const {
  gameState,
  slots,
  telnetHost,
  telnetPort,
  settingsOpen,
  showInfo,
  settingsSaving,
  applying,
  applyResult,
  clearing,
  testing,
  testResult,
  livePlayers,
  ctPlayers,
  tPlayers,
  allPlayerNames,
  sideForName,
  preCommand,
  previewCommand,
  numericNameWarnings,
  saveSettings,
  testConnection,
  applyBinds,
  clearBinds,
  quickAssign,
  clearSlot,
  fillFromCS2,
  SLOT_KEYS,
  buildCommand
} = useSpectator();
</script>

<template>
  <div class="p-6 bg-surface text-zinc-200 min-h-screen">
    <!-- Info modal -->
    <SpectatorInfoModal :show="showInfo" @close="showInfo = false" />

    <!-- Header -->
    <div class="flex items-start justify-between mb-6 gap-4">
      <div>
        <h1 class="text-2xl font-bold text-text-main flex items-center gap-2">
          观战按键绑定
          <BaseButton
            @click="showInfo = true"
            variant="ghost"
            size="sm"
            title="使用说明"
          >
            <InfoIcon/>
          </BaseButton>
        </h1>
        <p class="text-zinc-400 text-sm mt-1">
          把选手固定到数字键，并将按键设置发送给 CS2。
        </p>
        <BaseBadge variant="blue">
          使用前需要为参加比赛的每名选手设置位置。
        </BaseBadge>
      </div>

      <div class="flex items-center gap-2 shrink-0">
        <!-- CS2 telnet settings toggle -->
        <BaseButton
          @click="settingsOpen = !settingsOpen"
        >
          <SettingsIcon/>
          连接设置
        </BaseButton>

        <!-- Clear binds button -->
        <BaseButton
          @click="clearBinds"
          :disabled="clearing || applying"
          title="清空全部选手位置，并恢复 CS2 默认数字键"
        >
          <CloseIcon v-if="!clearing" class="w-4 h-4" />
          <RefreshIcon v-else name="refresh" class="w-4 h-4 animate-spin" />
          {{ clearing ? '正在清空...' : '全部清空' }}
        </BaseButton>

        <!-- Apply button -->
        <BaseButton
          @click="applyBinds"
          :disabled="applying"
          variant="primary"
        >
          {{ applying ? '正在应用...' : '应用到 CS2' }}
        </BaseButton>
      </div>
    </div>

    <!-- Telnet settings panel -->
    <SpectatorTelnetSettings
      v-if="settingsOpen"
      v-model:host="telnetHost"
      v-model:port="telnetPort"
      :testing="testing"
      :test-result="testResult"
      :saving="settingsSaving"
      @test="testConnection"
      @save="saveSettings"
    />

    <!-- Apply result toast -->
    <div
      v-if="applyResult"
      class="mb-5 px-4 py-3 rounded-lg text-sm font-medium border"
      :class="applyResult.ok
        ? 'bg-emerald-900/30 border-emerald-700/50 text-emerald-300'
        : 'bg-red-900/30 border-red-700/50 text-red-300'"
    >
      {{ applyResult.message }}
    </div>

    <!-- Warning: player names starting with a number don't work with spec_player -->
    <div
      v-if="numericNameWarnings.length"
      class="mb-5 flex items-start gap-3 px-4 py-3 rounded-lg border bg-red-900/20 border-red-700/40 text-red-300 text-sm"
    >
      <WarningIcon/>
      <span>
        名字以数字开头的选手<span class="font-semibold">无法使用按键绑定</span>，这是 CS2 本身的限制。
        <br>
        <span>受影响的选手：<span class="font-mono">{{ numericNameWarnings.join(', ') }}</span>。</span>
      </span>
    </div>

    <div class="flex flex-col gap-5">
      <!-- Slot Grid -->
      <SpectatorSlotGrid
        :slots="slots"
        :live-players="livePlayers"
        :all-player-names="allPlayerNames"
        :side-for-name="sideForName"
        :slot-keys="SLOT_KEYS"
        @clear-slot="clearSlot"
        @fill-from-cs2="fillFromCS2"
      />

      <!-- Live Players -->
      <SpectatorLivePlayers
        :game-state="gameState"
        :live-players="livePlayers"
        :ct-players="ctPlayers"
        :t-players="tPlayers"
        @quick-assign="quickAssign"
      />

      <!-- Pre-command (optional alias to run before each player bind) -->
      <div class="bg-zinc-800 border border-zinc-700 rounded-xl p-4">
        <div class="space-y-3">
          <div>
            <label class="block text-sm font-semibold text-zinc-300">
              绑定前执行的命令 <span class="text-zinc-500 font-normal">（可选）</span>
            </label>
            <p class="text-xs text-zinc-500 mt-0.5">
              每次切换选手前先执行的命令，例如用 <code class="text-zinc-400">reset_cams</code> 重置 HLAE 镜头。
            </p>
          </div>
          <BaseInput
            v-model="preCommand"
            placeholder="例如：reset_cams"
            size="md"
          />
        </div>
      </div>

      <!-- Command Preview -->
      <SpectatorCommandPreview
        v-if="Object.values(slots).some(v => v)"
        :preview-command="previewCommand"
        :build-command="buildCommand"
      />
    </div>
  </div>
</template>
