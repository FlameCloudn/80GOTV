<script setup lang="ts">
// OBS 浏览器源：把这个地址填进 OBS 的“浏览器”来源，HUD 就会出现在直播画面上
import AppIcon from '../../../components/ui/AppIcon.vue'

defineProps<{ url: string }>()
const emit = defineEmits<{ copy: []; preview: [] }>()
</script>

<template>
  <section class="panel dock-panel">
    <div class="panel-head"><b>OBS 浏览器源</b></div>
    <div class="obs-row">
      <input class="input num" :value="url" readonly aria-label="OBS 浏览器源地址" @focus="($event.target as HTMLInputElement).select()" />
      <button type="button" class="icon-btn" title="复制地址" @click="emit('copy')"><AppIcon name="copy" /></button>
      <button type="button" class="icon-btn" title="在浏览器里预览 HUD" @click="emit('preview')"><AppIcon name="eye" /></button>
    </div>
  </section>
</template>

<style scoped>
.dock-panel { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.obs-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; }
.obs-row .input { height: 30px; font-size: 11px; color: var(--text-2); }
</style>
