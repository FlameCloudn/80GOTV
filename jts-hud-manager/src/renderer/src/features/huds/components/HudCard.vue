<script setup lang="ts">
// 一个 HUD：缩略图、名称版本、是否已验证；启动导播画面、复制 OBS 地址、控制面板、其他布局、删除（点两次确认）
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../../../components/ui/AppIcon.vue'
import type { HudData } from '../composables/useHuds'
import { showToast } from '../../../composables/useToasts'

const props = defineProps<{ hud: HudData }>()
const emit = defineEmits<{ delete: [id: string] }>()

const router = useRouter()
const showVariants = ref(false)
const isConfirmDelete = ref(false)
const isDeleting = ref(false)

const buildUrl = (url: string, variant?: string): string => {
  if (!variant) return url
  return `${url}${url.includes('?') ? '&' : '?'}variant=${encodeURIComponent(variant)}`
}

const launchHud = (url: string, variant?: string) => {
  const finalUrl = buildUrl(url, variant)
  if (window.electron?.ipcRenderer) window.electron.ipcRenderer.send('open-hud', finalUrl)
  else window.open(finalUrl, '_blank')
}

const copyUrl = async (url: string) => {
  try {
    if (window.api?.copyText) await window.api.copyText(url)
    else await navigator.clipboard.writeText(url)
    showToast('OBS 地址已复制', 'success', { key: 'hud-copy' })
  } catch {
    showToast('复制失败，请手动选中地址复制', 'error', { key: 'hud-copy' })
  }
}

// 第一次点变成“确认删除？”，3 秒内再点才真的删
const handleDelete = () => {
  if (!isConfirmDelete.value) {
    isConfirmDelete.value = true
    setTimeout(() => (isConfirmDelete.value = false), 3000)
    return
  }
  isDeleting.value = true
  isConfirmDelete.value = false
  emit('delete', props.hud.id)
}

const otherVariants = props.hud.config.variants?.filter((variant) => variant.toLowerCase() !== 'main') ?? []
</script>

<template>
  <article class="panel hud-card">
    <div class="thumb">
      <img v-if="hud.thumb" :src="hud.thumb" :alt="hud.config.name" />
      <AppIcon v-else name="image" class="thumb-empty" />
    </div>
    <div class="hud-body">
      <div class="hud-title">
        <b>{{ hud.config.name || (hud.id === 'default' ? '80GOTV 内置 HUD' : hud.id) }}</b>
        <span v-if="hud.config.version" class="tag tag-accent num">v{{ hud.config.version }}</span>
        <span v-if="hud.isSigned && hud.signatureVerified" class="tag tag-ok"><AppIcon name="check" />已验证</span>
        <span v-else-if="hud.isSigned" class="tag tag-warn" title="这个 HUD 带有签名，但无法验证，文件可能被改过">未验证</span>
      </div>
      <p class="hint">作者：{{ hud.config.author || '未知' }}</p>

      <div class="hud-actions">
        <button type="button" class="btn btn-primary" @click="launchHud(hud.url)"><AppIcon name="play" />启动导播画面</button>
        <button type="button" class="btn" @click="copyUrl(hud.url)"><AppIcon name="copy" />复制 OBS 地址</button>
        <button v-if="hud.hasPanel" type="button" class="btn" @click="router.push(`/huds/${hud.id}/panel`)"><AppIcon name="sliders" />控制面板</button>
        <button v-if="otherVariants.length" type="button" class="btn btn-ghost" @click="showVariants = !showVariants">
          <AppIcon name="chevronDown" :class="{ flipped: showVariants }" />其他布局
        </button>
        <button
          v-if="hud.canDelete !== false"
          type="button"
          class="btn delete-btn"
          :class="{ 'btn-danger': isConfirmDelete }"
          :disabled="isDeleting"
          @click="handleDelete"
        >
          <AppIcon :name="isConfirmDelete ? 'alert' : 'trash'" />{{ isConfirmDelete ? '确认删除？' : isDeleting ? '删除中…' : '删除' }}
        </button>
      </div>

      <div v-if="otherVariants.length && showVariants" class="variants">
        <div v-for="variant in otherVariants" :key="variant" class="variant">
          <button type="button" class="variant-launch" @click="launchHud(hud.url, variant)">{{ variant }}</button>
          <button type="button" class="variant-copy" title="复制这个布局的地址" @click="copyUrl(buildUrl(hud.url, variant))"><AppIcon name="copy" /></button>
        </div>
      </div>
    </div>
  </article>
</template>

<style scoped>
.hud-card { display: flex; gap: 16px; padding: 14px; }
.thumb { width: 192px; aspect-ratio: 16 / 9; flex: none; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-md); background: var(--bg-input); border: 1px solid var(--border); }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.thumb-empty { width: 28px; height: 28px; color: var(--text-3); }
.hud-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.hud-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hud-title b { font-size: 16px; }
.hud-title .tag .icon { width: 12px; height: 12px; }
.hud-actions { margin-top: auto; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.delete-btn { margin-left: auto; }
.flipped { transform: rotate(180deg); }
.variants { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 10px; border-top: 1px solid var(--border); }
.variant { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--radius-md); overflow: hidden; }
.variant-launch { height: 28px; padding: 0 12px; border: none; background: var(--bg-raised); color: var(--text-2); font-size: 12px; font-weight: 600; }
.variant-launch:hover { background: var(--accent-soft); color: var(--text); }
.variant-copy { width: 30px; height: 28px; display: grid; place-items: center; border: none; border-left: 1px solid var(--border-strong); background: var(--bg-raised); color: var(--text-3); }
.variant-copy:hover { color: var(--text); background: var(--bg-hover); }
.variant-copy .icon { width: 13px; height: 13px; }
</style>
