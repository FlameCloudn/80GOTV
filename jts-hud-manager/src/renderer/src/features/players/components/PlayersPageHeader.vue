<script setup lang="ts">
// 选手页标题行：导入 / 导出 Excel、全部删除、添加选手
import AppIcon from '../../../components/ui/AppIcon.vue'
import PageHeader from '../../../components/ui/PageHeader.vue'

defineProps<{ playersCount: number }>()
defineEmits<{ import: []; export: []; deleteAll: []; add: [] }>()
</script>

<template>
  <PageHeader kicker="Players" title="选手" description="管理选手资料、头像和所属战队">
    <button type="button" class="btn" title="从 Excel 导入选手" @click="$emit('import')"><AppIcon name="upload" />导入</button>
    <button type="button" class="btn" title="导出为 Excel" @click="$emit('export')"><AppIcon name="download" />导出</button>
    <button type="button" class="btn btn-danger" :disabled="playersCount === 0" @click="$emit('deleteAll')"><AppIcon name="trash" />全部删除</button>
    <button type="button" class="btn btn-primary" @click="$emit('add')"><AppIcon name="plus" />添加选手</button>
  </PageHeader>
</template>
