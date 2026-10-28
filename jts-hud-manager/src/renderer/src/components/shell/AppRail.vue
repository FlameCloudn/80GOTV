<script setup lang="ts">
// 左侧图标栏：导播相关在上，资料在下，设置在最底
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import type { IconName } from '../ui/icons'
import SettingsModal from '../base/SettingsModal.vue'
import { useDirectorStatus } from '../../composables/useDirectorStatus'
import brandMark from '../../assets/80gotv-mark.png'

type RailLink = { to: string; label: string; title: string; icon: IconName; live?: boolean }

const groups: RailLink[][] = [
  [
    { to: '/director', label: '导播台', title: '导播台：切换场景、连接网站', icon: 'monitor' },
    { to: '/live', label: '实时', title: '实时数据：看 CS2 传来的选手', icon: 'activity', live: true },
    { to: '/spectator', label: '观战', title: '观战按键：把选手绑到数字键', icon: 'crosshair' }
  ],
  [
    { to: '/matches', label: '比赛', title: '比赛', icon: 'calendar' },
    { to: '/teams', label: '战队', title: '战队', icon: 'users' },
    { to: '/players', label: '选手', title: '选手', icon: 'user' },
    { to: '/huds', label: 'HUD', title: '导播 HUD', icon: 'layers' }
  ]
]

const route = useRoute()
const settingsOpen = ref(false)
const { cs2Fresh } = useDirectorStatus()
const isActive = (to: string) => route.path === to || route.path.startsWith(`${to}/`)
</script>

<template>
  <aside class="rail">
    <img class="rail-logo" :src="brandMark" alt="80GOTV" title="80GOTV 导播" />
    <template v-for="(group, index) in groups" :key="index">
      <span v-if="index" class="rail-sep" />
      <router-link
        v-for="item in group"
        :key="item.to"
        :to="item.to"
        class="rail-item"
        :class="{ active: isActive(item.to) }"
        :title="item.title"
      >
        <AppIcon :name="item.icon" />
        <span>{{ item.label }}</span>
        <span v-if="item.live && cs2Fresh" class="rail-dot" title="正在接收 CS2 数据" />
      </router-link>
    </template>
    <button type="button" class="rail-item rail-foot" title="设置" @click="settingsOpen = true">
      <AppIcon name="sliders" />
      <span>设置</span>
    </button>
    <SettingsModal :open="settingsOpen" @close="settingsOpen = false" />
  </aside>
</template>

<style scoped>
.rail { height: 100vh; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px 0; background: var(--bg-panel); border-right: 1px solid var(--border); }
.rail-logo { width: 36px; height: 36px; border-radius: 8px; margin-bottom: 10px; }
.rail-item { position: relative; width: 62px; height: 54px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; border: none; border-radius: var(--radius-md); background: transparent; color: var(--text-3); font-size: 11px; text-decoration: none; transition: background-color 0.12s, color 0.12s; }
.rail-item .icon { width: 20px; height: 20px; }
.rail-item:hover { background: var(--bg-hover); color: var(--text); }
.rail-item.active { background: var(--accent-soft); color: var(--text); }
.rail-item.active .icon { color: var(--accent); }
.rail-item.active::before { content: ''; position: absolute; left: -7px; top: 14px; bottom: 14px; width: 3px; border-radius: 2px; background: var(--accent); }
.rail-dot { position: absolute; top: 9px; right: 16px; width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 2px var(--bg-panel); }
.rail-sep { width: 32px; height: 1px; background: var(--border); margin: 6px 0; }
.rail-foot { margin-top: auto; }
</style>
