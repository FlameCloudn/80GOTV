<script setup lang="ts">
// 编辑用的弹窗：标题 + 内容（表单）+ 底部“取消 / 保存更改”。保存按钮提交 formId 指定的表单。
import AppIcon from '../ui/AppIcon.vue'

defineProps<{
  isOpen: boolean
  title: string
  formId?: string
  maxWidthClass?: string
}>()
defineEmits(['close', 'cancel'])
</script>

<template>
  <div v-if="isOpen" class="dialog-backdrop">
    <div class="dialog" :class="maxWidthClass || 'max-w-md'" role="dialog" :aria-label="title">
      <div class="dialog-head">
        <h2>{{ title }}</h2>
        <button type="button" class="icon-btn dialog-close" title="关闭" @click="$emit('close')"><AppIcon name="x" /></button>
      </div>
      <div class="dialog-body">
        <slot />
      </div>
      <div class="dialog-foot">
        <button type="button" class="btn" @click="$emit('cancel')">取消</button>
        <button :form="formId" type="submit" class="btn btn-primary">保存更改</button>
      </div>
    </div>
  </div>
</template>
