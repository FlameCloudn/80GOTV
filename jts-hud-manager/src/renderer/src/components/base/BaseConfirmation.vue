<script setup lang="ts">
import { useConfirmation } from '../../composables/useConfirmation';

const { isOpen, message, confirmLabel, secondaryLabel, onConfirm, onSecondary, onCancel } = useConfirmation();
</script>

<template>
  <Transition name="fade">
    <div v-if="isOpen" class="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div class="bg-zinc-800 border border-zinc-700 rounded-xl shadow-2xl w-full max-w-sm overflow-hidden">

        <div class="p-6">
          <div class="flex items-start gap-4">
            <div class="w-10 h-10 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center shrink-0">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
            </div>
            <div>
              <h3 class="text-base font-bold text-text-main">请确认操作</h3>
              <p class="text-sm text-zinc-400 mt-1">{{ message }}</p>
            </div>
          </div>
        </div>

        <div class="px-6 pb-6 flex flex-col gap-2">
          <!-- Two-choice layout when secondaryLabel is set, otherwise single confirm -->
          <div v-if="secondaryLabel" class="flex flex-col gap-2">
            <button
              @click="onConfirm"
              class="w-full bg-red-600 hover:bg-red-500 text-text-main font-semibold py-2 px-4 rounded-lg text-sm transition-colors"
            >
              {{ confirmLabel }}
            </button>
            <button
              @click="onSecondary"
              class="w-full bg-orange-600/80 hover:bg-orange-600 text-text-main font-semibold py-2 px-4 rounded-lg text-sm transition-colors"
            >
              {{ secondaryLabel }}
            </button>
            <button
              @click="onCancel"
              class="w-full bg-zinc-700 hover:bg-zinc-600 text-text-main font-semibold py-2 px-4 rounded-lg text-sm transition-colors"
            >
              取消
            </button>
          </div>
          <div v-else class="flex gap-3">
            <button
              @click="onCancel"
              class="flex-1 bg-zinc-700 hover:bg-zinc-600 text-text-main font-semibold py-2 px-4 rounded-lg text-sm transition-colors"
            >
              取消
            </button>
            <button
              @click="onConfirm"
              class="flex-1 bg-red-600 hover:bg-red-500 text-text-main font-semibold py-2 px-4 rounded-lg text-sm transition-colors"
            >
              {{ confirmLabel }}
            </button>
          </div>
        </div>

      </div>
    </div>
  </Transition>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
