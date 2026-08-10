<script setup lang="ts">
import CloseIcon from '@renderer/assets/icons/CloseIcon.vue';


defineProps<{
  show: boolean;
}>();

defineEmits<{
  (e: 'close'): void;
}>();
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      @click.self="$emit('close')"
    >
      <div class="bg-surface border border-zinc-700 rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        <!-- Modal header -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 class="text-lg font-bold text-text-main">观战按键使用说明</h2>
          <button @click="$emit('close')" class="text-zinc-500 hover:text-zinc-200 transition-colors">
            <CloseIcon name="close" class="size-6" />
          </button>
        </div>
        <!-- Modal body -->
        <div class="px-6 py-5 space-y-4 text-sm text-zinc-300 leading-relaxed overflow-y-auto max-h-[70vh]">
          <section class="bg-blue-950 p-1.5 rounded-lg">
            <h3 class="text-blue-300 font-semibold mb-1">开始前请注意：</h3>
            <ul class="text-xs list-decimal list-inside font-bold">
              <li>名字以数字开头的选手无法使用绑定命令，这是 CS2 本身的限制。</li>
              <br/>
              <li>使用这个工具可能影响比赛地图胜场统计，目前仍在修复。</li>
            </ul>
          </section>

          <section>
            <h3 class="text-text-main font-semibold mb-1">功能说明</h3>
            <p>这个页面可以把数字键 <code class="bg-zinc-800 px-1 rounded">1</code> 到 <code class="bg-zinc-800 px-1 rounded">0</code> 固定分配给指定选手。</p>
            <br/>
            <p>这只是导播显示层面的调整，不会修改游戏里的真实选手位置。程序会在数据发给 HUD 前重新对应选手，并让数字键切换到正确的人。</p>
          </section>

          <section>
            <h3 class="text-text-main font-semibold mb-1">分配选手</h3>
            <p>可以使用数字键下方的下拉框，也可以点击“当前比赛选手”快速加入第一个空位。“从 CS2 自动填写”会读取 GSI 数据中的 <code class="bg-zinc-800 px-1 rounded">observer_slot</code>。</p>
          </section>

          <section>
            <h3 class="text-text-main font-semibold mb-1">自动应用按键</h3>
            <p>在 CS2 启动项加入 <code class="bg-zinc-800 px-1 rounded font-mono">-netconport 2020</code> 后，点击“应用到 CS2”，程序就会自动发送按键命令。</p>
          </section>

          <section>
            <h3 class="text-text-main font-semibold mb-1">手动应用按键</h3>
            <p>如果自动连接不可用，可以在“命令预览”中点击“复制命令”，再粘贴到 CS2 控制台（<code class="bg-zinc-800 px-1 rounded">~</code>）。</p>
          </section>

          <section>
            <h3 class="text-text-main font-semibold mb-1">清空按键</h3>
            <p>“全部清空”会删除页面上的全部选手位置，解除观战绑定，并恢复默认武器数字键。单独清空某个按键只会恢复那一个数字键。</p>
          </section>

          <section>
            <h3 class="text-text-main font-semibold mb-1">CS2 启动项</h3>
            <p>在 Steam 的 CS2 启动项中加入：</p>
            <pre class="bg-zinc-950 border border-border rounded-lg px-3 py-2 font-mono text-xs text-zinc-400 mt-1">-netconport 2020</pre>
            <p class="text-zinc-500 text-xs mt-1">端口可以在本页面的“连接设置”中修改。</p>
          </section>
        </div>
      </div>
    </div>
  </Teleport>
</template>
