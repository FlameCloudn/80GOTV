<script setup lang="ts">
import BaseInput from '@renderer/components/base/BaseInput.vue';
import BaseButton from '@renderer/components/base/BaseButton.vue';

const props = defineProps<{
  host: string;
  port: number;
  testing: boolean;
  testResult: { ok: boolean; message: string } | null;
  saving: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:host', value: string): void;
  (e: 'update:port', value: number): void;
  (e: 'test'): void;
  (e: 'save'): void;
}>();
</script>

<template>
  <div class="mb-5 bg-zinc-800 border border-zinc-700 rounded-xl p-4">
    <h3 class="text-sm font-semibold text-zinc-300 mb-3">CS2 控制台连接</h3>
    <div class="flex flex-wrap items-end gap-3">
      <div class="w-40">
        <BaseInput
          :model-value="host"
          @update:model-value="emit('update:host', $event as string)"
          label="地址"
          placeholder="127.0.0.1"
          size="md"
        />
      </div>
      <div class="w-24">
        <BaseInput
          :model-value="port"
          @update:model-value="emit('update:port', Number($event))"
          label="Port"
          type="number"
          placeholder="2020"
          size="md"
        />
      </div>
      <BaseButton
        @click="$emit('test')"
        :disabled="testing"
        variant="secondary"
      >
        {{ testing ? '正在测试...' : '测试连接' }}
      </BaseButton>
      <BaseButton
        @click="$emit('save')"
        :disabled="saving"
        variant="primary"
      >
        {{ saving ? '正在保存...' : '保存' }}
      </BaseButton>
      <span
        v-if="testResult"
        class="text-sm font-medium"
        :class="testResult.ok ? 'text-emerald-400' : 'text-red-400'"
      >
        {{ testResult.message }}
      </span>
    </div>
    <p class="text-xs text-zinc-600 mt-3">
      请在 Steam 的 CS2 启动项中加入 <code class="text-zinc-400">-netconport 2020</code>，再启动游戏。
    </p>
  </div>
</template>
