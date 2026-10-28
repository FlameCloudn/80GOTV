<script setup lang="ts">
// 实时数据页标题行：和导播服务的实时连接是否正常
import PageHeader from '../../../components/ui/PageHeader.vue'

defineProps<{ isConnected: boolean }>()
</script>

<template>
  <PageHeader kicker="Live" title="实时数据" description="看 CS2 传来的选手，顺手补充选手资料">
    <span class="tag" :class="isConnected ? 'tag-ok' : 'tag-bad'">
      <span class="dot" :class="isConnected ? 'ok' : 'bad'" />{{ isConnected ? '已连接' : '未连接' }}
    </span>
  </PageHeader>
</template>
