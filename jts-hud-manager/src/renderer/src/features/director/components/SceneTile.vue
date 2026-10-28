<script setup lang="ts">
// 一个场景大按钮：点按钮切换；右下角眼睛按钮只预览不切换
import AppIcon from '../../../components/ui/AppIcon.vue'
import type { IconName } from '../../../components/ui/icons'

export type SceneKind = 'game' | 'pause' | 'bp' | 'half' | 'post'

defineProps<{
  label: string
  sub: string
  icon: IconName
  kind: SceneKind
  shortcut?: string
  active?: boolean
  flash?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ run: []; preview: [] }>()
</script>

<template>
  <div class="tile" :class="[kind, { 'on-air': active }]">
    <button type="button" class="tile-main" :disabled="disabled" :title="`切换到：${label}`" @click="emit('run')">
      <span class="tile-top">
        <span class="tile-icon"><AppIcon :name="icon" /></span>
        <span v-if="active" class="tile-state on">ON AIR</span>
        <span v-else-if="flash" class="tile-state sent">已发送</span>
        <span v-if="shortcut" class="kbd tile-key" :title="`快捷键 ${shortcut}`">{{ shortcut }}</span>
      </span>
      <b>{{ label }}</b>
      <small>{{ sub }}</small>
    </button>
    <button type="button" class="tile-eye" title="在浏览器里预览这个画面（不会切换直播）" @click="emit('preview')">
      <AppIcon name="eye" />
    </button>
  </div>
</template>

<style scoped>
/* 窗口高的时候按钮跟着变高（最矮 146px，最高 210px） */
.tile { --cat: var(--accent); position: relative; height: clamp(146px, 19vh, 210px); }
.tile.game { --cat: #6b9fd1; }
.tile.pause { --cat: #d1a64b; }
.tile.bp { --cat: #a990d9; }
.tile.half { --cat: #4cae7c; }
.tile.post { --cat: #3fb0bb; }
.tile-main { width: 100%; height: 100%; display: flex; flex-direction: column; align-items: flex-start; padding: 14px 52px 14px 14px; border-radius: var(--radius-lg); border: 1px solid var(--border); background: var(--bg-panel); color: var(--text); text-align: left; transition: border-color 0.12s, background-color 0.12s; }
.tile-main:hover:not(:disabled) { border-color: color-mix(in srgb, var(--cat) 55%, var(--border)); background: color-mix(in srgb, var(--cat) 5%, var(--bg-panel)); }
.tile-main:active:not(:disabled) { transform: translateY(1px); }
.tile-main:disabled { opacity: 0.55; cursor: progress; }
.tile-top { display: flex; align-items: center; gap: 8px; width: calc(100% + 38px); }
.tile-icon { width: 36px; height: 36px; flex: none; display: grid; place-items: center; border-radius: var(--radius-md); background: color-mix(in srgb, var(--cat) 16%, transparent); color: var(--cat); }
.tile-icon .icon { width: 19px; height: 19px; }
.tile-state { height: 19px; display: inline-flex; align-items: center; padding: 0 6px; border-radius: var(--radius-sm); font: 800 10px/1 'Montserrat', 'Microsoft YaHei UI', sans-serif; letter-spacing: 0.05em; }
.tile-state.on { background: var(--live); color: #fff; }
.tile-state.sent { background: var(--green-soft); color: #8fd3ad; }
.tile-key { margin-left: auto; max-width: 92px; overflow: hidden; text-overflow: ellipsis; }
.tile-main b { margin-top: auto; font-size: 16px; font-weight: 700; }
.tile-main small { margin-top: 2px; font-size: 12px; color: var(--text-3); }
.tile.on-air .tile-main { border: 2px solid var(--live); padding: 13px 51px 13px 13px; background: linear-gradient(180deg, rgba(239, 91, 82, 0.16), rgba(239, 91, 82, 0.03)), var(--bg-panel); box-shadow: 0 0 0 4px rgba(239, 91, 82, 0.13); }
.tile-eye { position: absolute; right: 12px; bottom: 12px; width: 30px; height: 30px; display: grid; place-items: center; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--bg-raised); color: var(--text-3); }
.tile-eye:hover { background: var(--bg-hover); color: var(--text); }
.tile-eye .icon { width: 15px; height: 15px; }
</style>
