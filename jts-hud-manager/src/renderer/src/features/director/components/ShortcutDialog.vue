<script setup lang="ts">
// 场景快捷键：点“录入”后按组合键，Esc 取消；切到别的程序（比如 CS2、OBS）也能用
import AppIcon from '../../../components/ui/AppIcon.vue'
import { SHORTCUT_COMMANDS } from '../composables/useDirectorShortcuts'

defineProps<{ bindings: Record<string, string>; recording: string | null }>()
const emit = defineEmits<{ close: []; record: [command: string]; clear: [command: string] }>()
</script>

<template>
  <div class="dialog-backdrop" @mousedown.self="emit('close')">
    <div class="dialog" role="dialog" aria-label="场景快捷键">
      <div class="dialog-head">
        <AppIcon name="keyboard" />
        <h2>场景快捷键</h2>
        <button type="button" class="icon-btn dialog-close" title="关闭" @click="emit('close')"><AppIcon name="x" /></button>
      </div>
      <div class="dialog-body">
        <p class="hint intro">点“录入”后直接按组合键（例如 Ctrl+F1），按 Esc 取消。新安装默认不绑定，切到 CS2 或 OBS 里也能用。</p>
        <div v-for="item in SHORTCUT_COMMANDS" :key="item.key" class="shortcut-row">
          <span class="shortcut-name">{{ item.label }}</span>
          <button
            type="button"
            class="shortcut-key"
            :class="{ recording: recording === item.key, empty: !bindings[item.key] }"
            @click="emit('record', item.key)"
          >
            {{ recording === item.key ? '请按组合键…' : bindings[item.key] || '录入' }}
          </button>
          <button
            type="button"
            class="icon-btn danger"
            :disabled="!bindings[item.key]"
            :title="`清除“${item.label}”的快捷键`"
            @click="emit('clear', item.key)"
          >
            <AppIcon name="x" />
          </button>
        </div>
      </div>
      <div class="dialog-foot">
        <button type="button" class="btn" @click="emit('close')">完成</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.intro { margin-bottom: 12px; line-height: 1.6; }
.shortcut-row { display: grid; grid-template-columns: minmax(0, 1fr) 160px 30px; align-items: center; gap: 8px; height: 42px; border-top: 1px solid var(--border); }
.shortcut-name { font-size: 13px; color: var(--text-2); }
.shortcut-key { height: 30px; border-radius: var(--radius-md); border: 1px solid var(--border-strong); background: var(--bg-input); color: var(--text); font: 600 12px/1 'Montserrat', 'Microsoft YaHei UI', sans-serif; }
.shortcut-key.empty { color: var(--text-3); font-weight: 500; }
.shortcut-key.recording { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
</style>
