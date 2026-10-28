<script setup lang="ts">
// 战队页标题行：导入 / 导出 Excel、全部删除、添加战队
import AppIcon from '../../../components/ui/AppIcon.vue'
import PageHeader from '../../../components/ui/PageHeader.vue'

defineProps<{ teamsCount: number }>()
defineEmits<{ import: []; export: []; deleteAll: []; add: [] }>()
</script>

<template>
  <PageHeader kicker="Teams" title="战队" description="管理战队名称、简称、队标和选手">
    <button type="button" class="btn" title="从 Excel 导入战队" @click="$emit('import')"><AppIcon name="upload" />导入</button>
    <button type="button" class="btn" title="导出为 Excel" @click="$emit('export')"><AppIcon name="download" />导出</button>
    <button type="button" class="btn btn-danger" :disabled="teamsCount === 0" @click="$emit('deleteAll')"><AppIcon name="trash" />全部删除</button>
    <button type="button" class="btn btn-primary" @click="$emit('add')"><AppIcon name="plus" />添加战队</button>
  </PageHeader>
</template>
