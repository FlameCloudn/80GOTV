<script setup lang="ts">
// 线条图标：<AppIcon name="eye" />，大小用 class 控制（默认 16px，见 main.css 的 .icon）
import { computed } from 'vue'
import { ICONS, type IconName } from './icons'

const props = defineProps<{ name: IconName }>()
const markup = computed(() => ICONS[props.name] || '')
</script>

<template>
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" v-html="markup" />
</template>
