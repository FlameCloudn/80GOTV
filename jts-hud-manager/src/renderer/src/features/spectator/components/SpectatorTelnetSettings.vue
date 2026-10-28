<script setup lang="ts">
// CS2 控制台连接：地址 + 端口；测试结果在右上角提示
import BaseInput from '../../../components/base/BaseInput.vue'

defineProps<{ host: string; port: number; testing: boolean; saving: boolean }>()
const emit = defineEmits<{
  (e: 'update:host', value: string): void
  (e: 'update:port', value: number): void
  (e: 'test'): void
  (e: 'save'): void
}>()
</script>

<template>
  <section class="panel panel-pad telnet">
    <div class="panel-head"><b>CS2 控制台连接</b></div>
    <div class="telnet-row">
      <BaseInput :model-value="host" label="地址" placeholder="127.0.0.1" class="host" @update:model-value="emit('update:host', String($event))" />
      <BaseInput :model-value="port" label="端口" type="number" placeholder="2020" class="port" @update:model-value="emit('update:port', Number($event))" />
      <button type="button" class="btn" :disabled="testing" @click="emit('test')">{{ testing ? '正在测试…' : '测试连接' }}</button>
      <button type="button" class="btn btn-primary" :disabled="saving" @click="emit('save')">{{ saving ? '正在保存…' : '保存' }}</button>
    </div>
    <p class="hint">在 Steam 里 CS2 的启动项加上 <code>-netconport 2020</code>，再启动游戏。</p>
  </section>
</template>

<style scoped>
.telnet { display: flex; flex-direction: column; gap: 10px; }
.telnet-row { display: flex; align-items: flex-end; gap: 10px; }
.host { width: 180px; }
.port { width: 100px; }
code { padding: 1px 5px; border-radius: var(--radius-sm); background: var(--bg-raised); font-family: Consolas, monospace; font-size: 12px; color: var(--text-2); }
</style>
