<script setup lang="ts">
// 命令预览：自动连接用不了时，复制这段命令粘到 CS2 控制台（~ 键）
import AppIcon from '../../../components/ui/AppIcon.vue'
import { showToast } from '../../../composables/useToasts'

const props = defineProps<{ previewCommand: string; buildCommand: () => string }>()

const copyPreview = async () => {
  const consoleLine = props.buildCommand().split('\n').join('; ')
  try {
    if (window.api?.copyText) await window.api.copyText(consoleLine)
    else await navigator.clipboard.writeText(consoleLine)
    showToast('命令已复制，粘到 CS2 控制台里回车即可', 'success', { key: 'spectator-copy' })
  } catch {
    showToast('复制失败，请手动选中命令复制', 'error', { key: 'spectator-copy' })
  }
}
</script>

<template>
  <section class="panel panel-pad preview">
    <div class="panel-head">
      <b>命令预览</b>
      <button type="button" class="btn btn-sm" @click="copyPreview"><AppIcon name="copy" />复制命令</button>
    </div>
    <pre>{{ previewCommand }}</pre>
  </section>
</template>

<style scoped>
.preview { display: flex; flex-direction: column; gap: 10px; }
pre { margin: 0; max-height: 180px; overflow-y: auto; padding: 10px 12px; border-radius: var(--radius-md); background: var(--bg-input); border: 1px solid var(--border); font: 12px/1.6 Consolas, monospace; color: var(--text-2); white-space: pre-wrap; word-break: break-all; }
</style>
