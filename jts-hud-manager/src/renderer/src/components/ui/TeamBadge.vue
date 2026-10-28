<script setup lang="ts">
// 队标：有图片显示图片（加载失败退回简称），没有就在圆圈里写简称（和网站一样）
import { ref, watch } from 'vue'

const props = withDefaults(defineProps<{ logo?: string; abbr?: string; size?: 'sm' | 'md' }>(), {
  logo: '',
  abbr: '?',
  size: 'md'
})

const broken = ref(false)
watch(() => props.logo, () => (broken.value = false))
</script>

<template>
  <span class="team-badge" :class="[size === 'sm' && 'sm', logo && !broken && 'has-logo']">
    <img v-if="logo && !broken" :src="logo" alt="" @error="broken = true" />
    <template v-else>{{ abbr }}</template>
  </span>
</template>
