<script setup lang="ts">
// 右上角浮动提示：叠放不重叠，太多时提示区内部滚动；空白处不挡鼠标
import AppIcon from '../ui/AppIcon.vue'
import type { IconName } from '../ui/icons'
import { useToasts, type ToastLevel } from '../../composables/useToasts'

const { toasts, dismissToast } = useToasts()
const ICON_BY_LEVEL: Record<ToastLevel, IconName> = { error: 'alert', warn: 'alert', info: 'info', success: 'check' }
</script>

<template>
  <div class="toast-stack" aria-live="polite">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="toast.level" role="alert">
      <AppIcon :name="ICON_BY_LEVEL[toast.level]" class="toast-icon" />
      <div class="toast-body">
        <strong>{{ toast.title }}</strong>
        <p>{{ toast.text }}</p>
      </div>
      <button type="button" class="toast-close" title="关闭" @click="dismissToast(toast.id)">
        <AppIcon name="x" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.toast-stack { position: fixed; top: 8px; right: 12px; z-index: 500; width: 340px; max-height: calc(100vh - 46px); overflow-y: auto; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { pointer-events: auto; display: flex; align-items: flex-start; gap: 10px; padding: 10px 10px 10px 12px; border-radius: var(--radius-md); background: #23272e; border: 1px solid var(--border-strong); box-shadow: 0 10px 28px rgba(0, 0, 0, 0.5); }
.toast.error { border-color: rgba(239, 91, 82, 0.65); }
.toast.warn { border-color: rgba(209, 166, 75, 0.6); }
.toast-icon { margin-top: 2px; }
.error .toast-icon { color: var(--live); }
.warn .toast-icon { color: var(--gold); }
.info .toast-icon { color: var(--accent); }
.success .toast-icon { color: var(--green); }
.toast-body { flex: 1; min-width: 0; }
.toast-body strong { display: block; font-size: 13px; color: var(--text); }
.toast-body p { margin: 2px 0 0; font-size: 12px; line-height: 1.5; color: var(--text-2); overflow-wrap: anywhere; white-space: pre-line; }
.toast-close { flex: none; width: 24px; height: 24px; display: grid; place-items: center; border: none; border-radius: var(--radius-sm); background: transparent; color: var(--text-3); }
.toast-close:hover { background: var(--bg-hover); color: var(--text); }
.toast-close .icon { width: 14px; height: 14px; }
</style>
