<script setup lang="ts">
// HUD 页标题行：刷新、导入 HUD（zip）
import { ref } from 'vue'
import AppIcon from '../../../components/ui/AppIcon.vue'
import PageHeader from '../../../components/ui/PageHeader.vue'

defineProps<{ importing: boolean; importError: string | null }>()
const emit = defineEmits<{ 'import-file': [file: File]; refresh: [] }>()

const zipInput = ref<HTMLInputElement | null>(null)
const onFileChange = (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  emit('import-file', file)
  if (zipInput.value) zipInput.value.value = ''
}
</script>

<template>
  <PageHeader kicker="HUD" title="导播 HUD" description="导入、管理并启动直播画面">
    <button type="button" class="btn" @click="emit('refresh')"><AppIcon name="refresh" />刷新</button>
    <button type="button" class="btn btn-primary" :disabled="importing" @click="zipInput?.click()">
      <AppIcon name="upload" />{{ importing ? '正在导入…' : '导入 HUD (.zip)' }}
    </button>
    <input ref="zipInput" type="file" accept=".zip" class="hidden-file" :disabled="importing" @change="onFileChange" />
  </PageHeader>
</template>

<style scoped>
.hidden-file { display: none; }
</style>
