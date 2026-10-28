<script setup lang="ts">
// HUD 控制面板标题行：返回 HUD 列表
import { useRouter } from 'vue-router'
import AppIcon from '../../../components/ui/AppIcon.vue'

defineProps<{ hudId: string }>()
const router = useRouter()
</script>

<template>
  <div class="page-head">
    <button type="button" class="icon-btn" title="返回 HUD 列表" @click="router.push('/huds')"><AppIcon name="chevronLeft" /></button>
    <div class="page-title"><div class="kicker">HUD Panel</div><h1>HUD 控制面板</h1></div>
    <span class="tag num">{{ hudId }}</span>
  </div>
</template>
