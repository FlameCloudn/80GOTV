<script setup lang="ts">
// 观战按键使用说明
import AppIcon from '../../../components/ui/AppIcon.vue'

defineProps<{ show: boolean }>()
defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="dialog-backdrop" @mousedown.self="$emit('close')">
      <div class="dialog info-dialog" role="dialog" aria-label="观战按键使用说明">
        <div class="dialog-head">
          <AppIcon name="info" />
          <h2>观战按键使用说明</h2>
          <button type="button" class="icon-btn dialog-close" title="关闭" @click="$emit('close')"><AppIcon name="x" /></button>
        </div>
        <div class="dialog-body info-body">
          <section class="notice">
            <b>开始前请注意</b>
            <ol>
              <li>名字以数字开头的选手无法使用绑定命令，这是 CS2 本身的限制。</li>
              <li>使用这个工具可能影响比赛地图胜场统计，目前仍在修复。</li>
            </ol>
          </section>
          <section>
            <h3>功能说明</h3>
            <p>把数字键 <code>1</code> 到 <code>0</code> 固定分给指定选手。这只改导播看到的对应关系，不会改游戏里的真实选手位置：程序在把数据发给 HUD 前重新对应选手，让数字键切到正确的人。</p>
          </section>
          <section>
            <h3>分配选手</h3>
            <p>用数字键下面的下拉框选人，或者点“当前比赛选手”里的名字放进第一个空键。“从 CS2 自动填写”会读取 GSI 数据里的 <code>observer_slot</code>。</p>
          </section>
          <section>
            <h3>自动应用</h3>
            <p>CS2 启动项加上 <code>-netconport 2020</code> 后，点“应用到 CS2”，程序会自动把按键命令发过去。</p>
          </section>
          <section>
            <h3>手动应用</h3>
            <p>自动连接用不了时，在“命令预览”里点“复制命令”，再粘到 CS2 控制台（<code>~</code> 键）里回车。</p>
          </section>
          <section>
            <h3>清空按键</h3>
            <p>“全部清空”会删掉页面上全部选手位置、解除观战绑定，并恢复默认武器数字键。单独清空某个键只恢复那一个数字键。</p>
          </section>
          <section>
            <h3>CS2 启动项</h3>
            <pre>-netconport 2020</pre>
            <p class="hint">端口可以在本页的“连接设置”里改。</p>
          </section>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.info-dialog { max-width: 540px; }
.info-body { display: flex; flex-direction: column; gap: 16px; font-size: 13px; line-height: 1.7; color: var(--text-2); }
.info-body h3 { margin-bottom: 2px; font-size: 13px; font-weight: 700; color: var(--text); }
.notice { padding: 10px 12px; border-radius: var(--radius-md); background: var(--accent-soft); border: 1px solid rgba(107, 159, 209, 0.35); }
.notice b { color: var(--accent); }
.notice ol { margin: 4px 0 0; padding-left: 18px; }
code { padding: 1px 5px; border-radius: var(--radius-sm); background: var(--bg-raised); font-family: Consolas, monospace; font-size: 12px; color: var(--text); }
pre { margin: 4px 0; padding: 8px 12px; border-radius: var(--radius-md); background: var(--bg-input); border: 1px solid var(--border); font: 12px/1.5 Consolas, monospace; color: var(--text-2); }
</style>
