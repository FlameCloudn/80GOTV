<script setup lang="ts">
import CheckIcon from '@renderer/assets/icons/CheckIcon.vue';
import CopyIcon from '@renderer/assets/icons/CopyIcon.vue';
import BaseButton from '@renderer/components/base/BaseButton.vue';
import { ref } from 'vue';

const props = defineProps<{
  previewCommand: string;
  buildCommand: () => string;
}>();

const copiedPreview = ref(false);
const copyPreview = async () => {
  const consoleLine = props.buildCommand().split('\n').join('; ');
  await navigator.clipboard.writeText(consoleLine);
  copiedPreview.value = true;
  setTimeout(() => { copiedPreview.value = false; }, 2000);
};
</script>

<template>
  <div class="mt-4">
    <div class="flex items-center justify-between mb-1.5">
      <div class="text-xs font-semibold uppercase tracking-widest text-zinc-600">命令预览</div>
      <BaseButton
        @click="copyPreview"
        size="sm"
        :variant="copiedPreview ? 'primary' : 'secondary'"
      >
        <CopyIcon v-if="!copiedPreview" name="copy" class="w-3 h-3" />
        <CheckIcon v-else name="check" class="w-3 h-3" />
        {{ copiedPreview ? '已复制！' : '复制命令' }}
      </BaseButton>
    </div>
    <pre class="bg-zinc-950 border border-border rounded-lg p-2.5 font-mono text-xs text-zinc-500 leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap break-all">{{ previewCommand }}</pre>
  </div>
</template>
