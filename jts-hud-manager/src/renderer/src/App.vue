<script setup lang="ts">
// 软件外壳：左边图标栏；右边上面节目条、中间页面、下面状态栏；右上角浮动提示
import { onBeforeUnmount, onMounted } from 'vue'
import BaseConfirmation from './components/base/BaseConfirmation.vue'
import AppRail from './components/shell/AppRail.vue'
import ProgramBar from './components/shell/ProgramBar.vue'
import StatusBar from './components/shell/StatusBar.vue'
import ToastStack from './components/shell/ToastStack.vue'
import { startDirectorStatus, stopDirectorStatus } from './composables/useDirectorStatus'

onMounted(startDirectorStatus)
onBeforeUnmount(stopDirectorStatus)
</script>

<template>
  <div class="app-shell">
    <AppRail />
    <div class="workspace">
      <ProgramBar />
      <main class="workspace-main">
        <router-view />
      </main>
      <StatusBar />
    </div>
    <ToastStack />
    <BaseConfirmation />
  </div>
</template>

<style scoped>
.app-shell { display: grid; grid-template-columns: 76px minmax(0, 1fr); height: 100vh; background: var(--bg); color: var(--text); }
.workspace { display: grid; grid-template-rows: 64px minmax(0, 1fr) 30px; height: 100vh; min-width: 0; }
.workspace-main { min-height: 0; overflow-y: auto; }
</style>
