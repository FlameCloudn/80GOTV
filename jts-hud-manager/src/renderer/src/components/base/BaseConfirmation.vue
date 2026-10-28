<script setup lang="ts">
// 删除 / 放弃修改的二次确认（这类确认照旧用确认框，不算错误提示）
import AppIcon from '../ui/AppIcon.vue'
import { useConfirmation } from '../../composables/useConfirmation'

const { isOpen, message, confirmLabel, secondaryLabel, onConfirm, onSecondary, onCancel } = useConfirmation()
</script>

<template>
  <Transition name="fade">
    <div v-if="isOpen" class="dialog-backdrop confirm-layer" @mousedown.self="onCancel">
      <div class="dialog confirm" role="alertdialog" aria-label="请确认操作">
        <div class="dialog-body confirm-body">
          <span class="confirm-icon"><AppIcon name="alert" /></span>
          <div>
            <h3>请确认操作</h3>
            <p>{{ message }}</p>
          </div>
        </div>
        <div v-if="secondaryLabel" class="dialog-foot confirm-foot stacked">
          <button type="button" class="btn btn-danger" @click="onConfirm">{{ confirmLabel }}</button>
          <button type="button" class="btn" @click="onSecondary">{{ secondaryLabel }}</button>
          <button type="button" class="btn btn-ghost" @click="onCancel">取消</button>
        </div>
        <div v-else class="dialog-foot confirm-foot">
          <button type="button" class="btn" @click="onCancel">取消</button>
          <button type="button" class="btn btn-danger" @click="onConfirm">{{ confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.confirm-layer { z-index: 400; }
.confirm { max-width: 380px; }
.confirm-body { display: flex; gap: 14px; padding: 20px; }
.confirm-icon { width: 38px; height: 38px; flex: none; display: grid; place-items: center; border-radius: 50%; background: var(--live-soft); color: var(--live); }
.confirm-body h3 { font-size: 15px; font-weight: 700; }
.confirm-body p { margin-top: 4px; font-size: 13px; line-height: 1.6; color: var(--text-2); }
.confirm-foot .btn { flex: 1; }
.confirm-foot.stacked { flex-direction: column; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
