<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import BaseButton from '../components/base/BaseButton.vue'
import { API_URL, LOCAL_SERVER_URL } from '../index'
import { socket } from '../socket'

type IntegrationStatus = {
  websiteUrl?: string
  selectedMatchId?: string | null
  importedMatchId?: string | null
  confirmedMatchId?: string | null
  forwardTargetMatchId?: string | null
  forwardLiveData?: boolean
  forwarding?: boolean
  forwardAttempts?: number
  lastLocalDataAt?: string | null
  lastForwardAt?: string | null
  lastConfirmedAt?: string | null
  lastConnectionTestAt?: string | null
  lastError?: string | null
}

type DirectorStatus = {
  scene: string
  visible: boolean
  hudClients: number
}

type CurrentMatch = {
  id?: string
  matchType?: string
  left?: { id?: string | null }
  right?: { id?: string | null }
}
type WebsiteMatchOption = { key: string; label: string; source_type?: string }

const integration = ref<IntegrationStatus | null>(null)
const director = ref<DirectorStatus>({ scene: 'auto', visible: true, hudClients: 0 })
const currentMatch = ref<CurrentMatch | null>(null)
const apiOnline = ref(false)
let lastSocketUpdate = 0
const now = ref(Date.now())
const commandBusy = ref(false)
const connectionBusy = ref(false)
const notice = ref<{ ok: boolean; text: string } | null>(null)
const shortcutBindings = ref<Record<string, string>>({})
const recordingShortcut = ref<string | null>(null)
const websiteMatches = ref<WebsiteMatchOption[]>([])
const selectedWebsiteMatch = ref('')
const userSelectedMatch = ref(false)
const lastAutoSyncKey = ref('')
const websiteSyncBusy = ref(false)
const websiteListBusy = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null
let matchListTimer: ReturnType<typeof setInterval> | null = null
let autoSyncTimer: ReturnType<typeof setTimeout> | null = null
let clockTimer: ReturnType<typeof setInterval> | null = null

const shortcutCommands = [
  { key: 'bp', label: 'BP' },
  { key: 'auto', label: '自动跟随' },
  { key: 'game', label: '比赛 HUD' },
  { key: 'pause_tactical', label: '战术暂停' },
  { key: 'pause_technical', label: '技术暂停' },
  { key: 'halftime', label: '中场' },
  { key: 'map_end', label: '单图结束' },
  { key: 'series_end', label: '系列赛结束' },
  { key: 'hide_all', label: '全部隐藏' }
]

const shortcutLabel = (key: string) => shortcutBindings.value[key] || '未设置'
const startRecordingShortcut = async (command: string) => {
  recordingShortcut.value = command
  if (window.api?.configureDirectorShortcuts) await window.api.configureDirectorShortcuts({})
}
const restoreShortcutBindings = () => {
  if (window.api?.configureDirectorShortcuts) void window.api.configureDirectorShortcuts(shortcutBindings.value)
}
const saveShortcuts = async (next: Record<string, string>) => {
  const result = window.api?.configureDirectorShortcuts
    ? await window.api.configureDirectorShortcuts(next)
    : { ok: true, errors: {} }
  if (!result.ok) throw new Error(Object.values(result.errors || {}).join('；') || '快捷键注册失败')
  const response = await fetch(`${API_URL}/settings`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ directorShortcuts: next })
  })
  if (!response.ok) throw new Error('快捷键保存失败')
  shortcutBindings.value = { ...next }
}
const recordShortcut = (event: KeyboardEvent) => {
  if (!recordingShortcut.value) return
  event.preventDefault(); event.stopPropagation()
  if (event.key === 'Escape') { recordingShortcut.value = null; restoreShortcutBindings(); return }
  const modifiers: string[] = []
  if (event.ctrlKey) modifiers.push('Ctrl')
  if (event.altKey) modifiers.push('Alt')
  if (event.shiftKey) modifiers.push('Shift')
  if (event.metaKey) modifiers.push('Super')
  const key = event.key.length === 1 ? event.key.toUpperCase() : event.key
  if (['Control', 'Alt', 'Shift', 'Meta'].includes(key)) return
  const accelerator = [...modifiers, key === ' ' ? 'Space' : key].join('+')
  const next = { ...shortcutBindings.value, [recordingShortcut.value]: accelerator }
  const duplicate = Object.entries(next).find(([command, value]) => command !== recordingShortcut.value && value.toLowerCase() === accelerator.toLowerCase())
  if (duplicate) { notice.value = { ok: false, text: `快捷键已被“${shortcutCommands.find((item) => item.key === duplicate[0])?.label || duplicate[0]}”使用` }; recordingShortcut.value = null; restoreShortcutBindings(); return }
  void saveShortcuts(next).then(() => { notice.value = { ok: true, text: `已绑定 ${accelerator}` } }).catch((error) => { restoreShortcutBindings(); notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) } }).finally(() => { recordingShortcut.value = null })
}
const clearShortcut = (command: string) => {
  const next = { ...shortcutBindings.value }; delete next[command]
  void saveShortcuts(next).then(() => { notice.value = { ok: true, text: '快捷键已清除' } }).catch((error) => { notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) } })
}
const loadShortcuts = async () => {
  try {
    const response = await fetch(`${API_URL}/settings`)
    if (!response.ok) return
    const settings = await response.json()
    const parsed = JSON.parse(settings.directorShortcuts || '{}')
    shortcutBindings.value = parsed && typeof parsed === 'object' ? parsed : {}
  } catch { shortcutBindings.value = {} }
}

const loadWebsiteMatches = async () => {
  websiteListBusy.value = true
  try {
    const response = await fetch(`${API_URL}/80gotv/matches`)
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.error || '读取网站比赛失败')
    const sources = payload.sources || payload.matches || []
    websiteMatches.value = sources
    const keys = sources.map((source: WebsiteMatchOption) => source.key)
    const preferred = selectedMatch.value
    selectedWebsiteMatch.value =
      !userSelectedMatch.value && keys.length
        ? keys[0]
        : preferred && keys.includes(preferred)
          ? preferred
          : keys[0] || ''
    const autoKey = selectedWebsiteMatch.value
    if (!userSelectedMatch.value && autoKey && autoKey !== lastAutoSyncKey.value) {
      lastAutoSyncKey.value = autoKey
      if (autoSyncTimer) clearTimeout(autoSyncTimer)
      autoSyncTimer = setTimeout(() => {
        if (selectedWebsiteMatch.value === autoKey && !websiteSyncBusy.value) {
          void syncWebsiteMatch()
        }
      }, 1500)
    }
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) }
  } finally { websiteListBusy.value = false }
}

const syncWebsiteMatch = async () => {
  if (!selectedWebsiteMatch.value) return
  websiteSyncBusy.value = true
  try {
    const response = await fetch(`${API_URL}/80gotv/sync`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ matchId: selectedWebsiteMatch.value })
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.error || '同步比赛资料失败')
    lastAutoSyncKey.value = selectedWebsiteMatch.value
    notice.value = { ok: true, text: `已同步：${payload.summary || selectedWebsiteMatch.value}` }
    await refreshStatus()
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) }
  } finally { websiteSyncBusy.value = false }
}

const toggleForwardLive = async () => {
  try {
    const response = await fetch(`${API_URL}/settings`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ forwardLiveData: !integration.value?.forwardLiveData })
    })
    if (!response.ok) throw new Error('实时上传设置保存失败')
    notice.value = { ok: true, text: integration.value?.forwardLiveData ? '已停止上传网站' : '已开启网站实时上传' }
    await refreshStatus()
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) }
  }
}

const sceneLabels: Record<string, string> = {
  auto: '自动跟随游戏',
  game: '比赛画面',
  pause_current: '战术暂停',
  pause_technical: '技术暂停',
  halftime: '中场',
  map_end: '单图结束',
  series_end: '整场结束'
}

const currentBoLabel = computed(() => {
  const value = String(currentMatch.value?.matchType || '').toUpperCase().match(/BO?([135])/)
  return value ? `BO${value[1]}` : '当前 BO'
})

const formatTime = (value?: string | null) => {
  if (!value) return '尚无'
  const date = new Date(value)
  return Number.isFinite(date.getTime())
    ? date.toLocaleTimeString('zh-CN', { hour12: false })
    : '尚无'
}

const ageOf = (value?: string | null) => {
  if (!value) return Number.POSITIVE_INFINITY
  const time = new Date(value).getTime()
  return Number.isFinite(time) ? now.value - time : Number.POSITIVE_INFINITY
}

const cs2Fresh = computed(() => {
  const statusAge = ageOf(integration.value?.lastLocalDataAt)
  const socketAge = lastSocketUpdate ? now.value - lastSocketUpdate : Number.POSITIVE_INFINITY
  return Math.min(statusAge, socketAge) <= 5000
})

const selectedMatch = computed(() => integration.value?.selectedMatchId || null)
const websiteConfirmed = computed(() => {
  const value = integration.value
  if (!value?.lastConnectionTestAt || !selectedMatch.value) return false
  return ageOf(value.lastConnectionTestAt) <= 10 * 60 * 1000
})
const uploadConfirmed = computed(() => {
  const value = integration.value
  return Boolean(
    value?.lastConfirmedAt &&
      value.confirmedMatchId &&
      value.confirmedMatchId === selectedMatch.value &&
      ageOf(value.lastConfirmedAt) <= 10000
  )
})

const activeSceneLabel = computed(() => {
  if (!director.value.visible) return '全部隐藏'
  return sceneLabels[director.value.scene] || director.value.scene
})

const matchLabel = computed(() => {
  if (!currentMatch.value) return '本地比赛未同步'
  const left = currentMatch.value.left?.id || '左队'
  const right = currentMatch.value.right?.id || '右队'
  return `${left} vs ${right} · ${(currentMatch.value.matchType || '').toUpperCase()}`
})

const browserSourceUrl = computed(
  () => `${LOCAL_SERVER_URL}/huds/default/index.html?isProd=1&v=80gotv-cn-obs-9`
)

const copyBrowserSource = async () => {
  notice.value = null
  try {
    if (window.api?.copyText) {
      await window.api.copyText(browserSourceUrl.value)
    } else {
      await navigator.clipboard.writeText(browserSourceUrl.value)
    }
    notice.value = { ok: true, text: 'OBS 浏览器源地址已复制' }
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : '复制失败' }
  }
}

const refreshStatus = async () => {
  try {
    const [integrationResponse, directorResponse, matchResponse] = await Promise.all([
      fetch(`${API_URL}/80gotv/status`),
      fetch(`${API_URL}/huds/default/director-status`),
      fetch(`${API_URL}/match/current`)
    ])
    apiOnline.value = integrationResponse.ok && directorResponse.ok
    if (integrationResponse.ok) integration.value = await integrationResponse.json()
    if (directorResponse.ok) director.value = await directorResponse.json()
    currentMatch.value = matchResponse.ok ? await matchResponse.json() : null
  } catch (error) {
    apiOnline.value = false
    console.error('[Director] status refresh failed', { apiUrl: API_URL, error })
  }
}

const sendDirectorCommand = async (command: string) => {
  const response = await fetch(`${API_URL}/huds/default/director-command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command })
  })
  const payload = await response.json()
  if (!response.ok || !payload.ok) throw new Error(payload.error || '场景指令发送失败')
}

const runScene = async (scene: string) => {
  commandBusy.value = true
  notice.value = null
  try {
    await sendDirectorCommand(scene)
    director.value = { ...director.value, scene, visible: true }
    notice.value = { ok: true, text: `已切换：${sceneLabels[scene] || scene}` }
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) }
  } finally {
    commandBusy.value = false
    await refreshStatus()
  }
}

const showBp = async () => {
  commandBusy.value = true
  notice.value = null
  try {
    await sendDirectorCommand('bp')
    director.value = { ...director.value, scene: 'game', visible: true }
    notice.value = { ok: true, text: '已展示 BP' }
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) }
  } finally {
    commandBusy.value = false
  }
}

const hideEverything = async () => {
  commandBusy.value = true
  notice.value = null
  try {
    await sendDirectorCommand('hide_all')
    director.value = { ...director.value, visible: false }
    notice.value = { ok: true, text: 'HUD 已全部隐藏' }
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) }
  } finally {
    commandBusy.value = false
    await refreshStatus()
  }
}

const testConnection = async () => {
  connectionBusy.value = true
  notice.value = null
  try {
    const response = await fetch(`${API_URL}/80gotv/connection-test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ matchId: selectedMatch.value })
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.error || '连接检查失败')
    const connection = payload.connection || {}
    notice.value = {
      ok: true,
      text: `网站已确认比赛 ${connection.match_id || selectedMatch.value}${connection.team1_name && connection.team2_name ? ` · ${connection.team1_name} vs ${connection.team2_name}` : ''}`
    }
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : String(error) }
  } finally {
    connectionBusy.value = false
    await refreshStatus()
  }
}

const openPreview = (query = '') => {
  const params = new URLSearchParams(query)
  params.set('isProd', '1')
  const url = `${LOCAL_SERVER_URL}/huds/default/index.html?${params.toString()}`
  if (window.api?.openExternal) window.api.openExternal(url)
  else window.open(url, '_blank')
}

const onGameUpdate = () => {
  lastSocketUpdate = Date.now()
}

onMounted(async () => {
  window.addEventListener('keydown', recordShortcut, true)
  socket.on('update', onGameUpdate)
  await loadShortcuts()
  await refreshStatus()
  await loadWebsiteMatches()
  pollTimer = setInterval(refreshStatus, 2000)
  matchListTimer = setInterval(loadWebsiteMatches, 30000)
  clockTimer = setInterval(() => { now.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  if (recordingShortcut.value) restoreShortcutBindings()
  window.removeEventListener('keydown', recordShortcut, true)
  socket.off('update', onGameUpdate)
  if (pollTimer) clearInterval(pollTimer)
  if (matchListTimer) clearInterval(matchListTimer)
  if (autoSyncTimer) clearTimeout(autoSyncTimer)
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<template>
  <div class="director-page">
    <header class="director-header">
      <div>
        <p class="director-kicker">80GOTV BROADCAST CONTROL</p>
        <h1>导播台</h1>
      </div>
      <div class="active-output" :class="director.visible ? 'is-live' : 'is-hidden'">
        <span class="status-dot" />
        <div>
          <small>当前输出</small>
          <strong>{{ activeSceneLabel }}</strong>
        </div>
      </div>
    </header>

    <section class="connection-strip">
      <div class="connection-cell" :class="apiOnline ? 'ok' : 'bad'">
        <span class="status-dot" />
        <div><small>导播服务</small><strong>{{ apiOnline ? '正常' : '未启动' }}</strong></div>
      </div>
      <div class="connection-cell" :class="cs2Fresh ? 'ok' : 'idle'">
        <span class="status-dot" />
        <div><small>CS2 数据</small><strong>{{ cs2Fresh ? '正在接收' : '等待游戏' }}</strong></div>
      </div>
      <div class="connection-cell" :class="websiteConfirmed ? 'ok' : selectedMatch ? 'warn' : 'bad'">
        <span class="status-dot" />
        <div><small>网站连接</small><strong>{{ websiteConfirmed ? '检查通过' : selectedMatch ? '尚未检查' : '未选比赛' }}</strong></div>
      </div>
      <div class="connection-cell" :class="director.hudClients > 0 ? 'ok' : 'warn'">
        <span class="status-dot" />
        <div><small>OBS / HUD</small><strong>{{ director.hudClients > 0 ? `${director.hudClients} 个画面在线` : '没有画面连接' }}</strong></div>
      </div>
      <BaseButton @click="testConnection" :disabled="connectionBusy || !selectedMatch" variant="secondary" size="sm" class="check-button">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
        {{ connectionBusy ? '检查中' : '检查完整连接' }}
      </BaseButton>
    </section>

    <section class="match-band">
      <div>
        <small>本地比赛</small>
        <strong>{{ matchLabel }}</strong>
      </div>
      <div>
        <small>网站比赛</small>
        <div class="website-match-controls">
          <select v-model="selectedWebsiteMatch" aria-label="选择网站比赛" @change="userSelectedMatch = true">
            <option value="">未选择</option>
            <option v-for="source in websiteMatches" :key="source.key" :value="source.key">{{ source.label }}</option>
          </select>
          <button title="读取网站比赛" :disabled="websiteListBusy" @click="loadWebsiteMatches">{{ websiteListBusy ? '读取中' : '读取' }}</button>
          <button title="同步比赛资料" :disabled="websiteSyncBusy || !selectedWebsiteMatch" @click="syncWebsiteMatch">{{ websiteSyncBusy ? '同步中' : '同步' }}</button>
        </div>
      </div>
      <div>
        <small>最近网站确认</small>
        <strong :class="uploadConfirmed ? 'text-emerald-300' : ''">{{ formatTime(integration?.lastConfirmedAt || integration?.lastConnectionTestAt) }}</strong>
      </div>
      <div v-if="integration?.lastError" class="match-error">{{ integration.lastError }}</div>
    </section>

    <section class="browser-source-band">
      <div>
        <small>OBS 浏览器源</small>
        <input :value="browserSourceUrl" readonly aria-label="OBS 浏览器源地址" />
      </div>
      <button title="复制浏览器源地址" @click="copyBrowserSource">
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="1"/><path d="M16 8V5H5v11h3"/></svg>
        <span>复制</span>
      </button>
      <button title="打开浏览器源预览" @click="openPreview()">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></svg>
        <span>预览</span>
      </button>
    </section>

    <main class="director-workspace">
      <section class="control-surface">
        <div class="surface-title">
          <div><small>SCENE CONTROL</small><h2>分步场景</h2></div>
          <span>不会自动跳到下一步</span>
        </div>

        <div class="scene-row">
          <div class="scene-number">01</div>
          <div class="scene-copy"><strong>赛前 BP</strong><span>地图选择锁定后由导播展示</span></div>
          <button class="scene-button bp" :disabled="commandBusy" @click="showBp">
            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7Z" /></svg><span>展示 BP</span>
          </button>
          <button class="preview-button" title="预览 BP" @click="openPreview('bpPreview=1')">
            <svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></svg>
          </button>
        </div>

        <div class="scene-row active-row split-row">
          <div class="scene-number">02</div>
          <div class="scene-copy"><strong>比赛与自动控制</strong><span>自动识别暂停和中场；切出覆盖层可强制只保留比赛 HUD</span></div>
          <div class="split-actions">
            <button class="scene-button auto" :disabled="commandBusy" @click="runScene('auto')">自动跟随</button>
            <button class="scene-button game" :disabled="commandBusy" @click="runScene('game')">切出覆盖层</button>
          </div>
          <button class="preview-button" title="打开 HUD 画面" @click="openPreview()">
            <svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></svg>
          </button>
        </div>

        <div class="scene-row split-row">
          <div class="scene-number">03</div>
          <div class="scene-copy"><strong>暂停</strong><span>战术暂停和技术暂停分别控制</span></div>
          <div class="split-actions">
            <button class="scene-button tactical" :disabled="commandBusy" @click="runScene('pause_current')">战术暂停</button>
            <button class="scene-button technical" :disabled="commandBusy" @click="runScene('pause_technical')">技术暂停</button>
          </div>
          <button class="preview-button" title="预览暂停" @click="openPreview('pausePreview=tactical')">
            <svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></svg>
          </button>
        </div>

        <div class="scene-row">
          <div class="scene-number">04</div>
          <div class="scene-copy"><strong>中场</strong><span>半场比分、选手数据与倒计时</span></div>
          <button class="scene-button halftime" :disabled="commandBusy" @click="runScene('halftime')">展示中场</button>
          <button class="preview-button" title="预览中场" @click="openPreview('halftimePreview=1')">
            <svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></svg>
          </button>
        </div>

        <div class="scene-row split-row">
          <div class="scene-number">05</div>
          <div class="scene-copy"><strong>赛后</strong><span>单图结果与整场 {{ currentBoLabel }} 总结分别展示</span></div>
          <div class="split-actions">
            <button class="scene-button map-end" :disabled="commandBusy" @click="runScene('map_end')">单图结束</button>
            <button class="scene-button series-end" :disabled="commandBusy" @click="runScene('series_end')">{{ currentBoLabel }} 结束</button>
          </div>
          <button class="preview-button" title="预览赛后" @click="openPreview('victoryPreview=1')">
            <svg viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></svg>
          </button>
        </div>
      </section>

      <aside class="safety-panel">
        <div class="safety-head"><small>OUTPUT SAFETY</small><strong>直播保险</strong></div>
        <button class="panic-button" :disabled="commandBusy" @click="hideEverything">
          <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg>
          <span><strong>全部隐藏</strong><small>紧急切回纯游戏画面</small></span>
        </button>
        <div class="safety-list">
          <div><span>实时上传</span><strong :class="integration?.forwardLiveData ? 'good' : 'muted'">{{ integration?.forwardLiveData ? '已开启' : '未开启' }}</strong></div>
          <div><span>上传目标</span><strong>{{ integration?.forwardTargetMatchId || '无' }}</strong></div>
          <div><span>重试次数</span><strong :class="integration?.forwardAttempts ? 'warning' : ''">{{ integration?.forwardAttempts || 0 }}</strong></div>
          <div><span>最后接收 CS2</span><strong>{{ formatTime(integration?.lastLocalDataAt) }}</strong></div>
        </div>
        <button class="upload-toggle" :class="integration?.forwardLiveData ? 'enabled' : ''" @click="toggleForwardLive">
          {{ integration?.forwardLiveData ? '停止网站实时上传' : '开启网站实时上传' }}
        </button>
        <BaseButton @click="refreshStatus" variant="ghost" size="sm" class="refresh-button">
          <svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></svg>
          刷新状态
        </BaseButton>
        <div class="shortcut-panel">
          <div class="safety-head shortcut-head"><small>GLOBAL SHORTCUTS</small><strong>场景快捷键</strong></div>
          <p class="shortcut-note">新安装默认不绑定。点击录入后按组合键，按 Esc 取消。</p>
          <div v-for="item in shortcutCommands" :key="item.key" class="shortcut-row">
            <span>{{ item.label }}</span>
            <button class="shortcut-key" :class="recordingShortcut === item.key ? 'recording' : ''" @click="startRecordingShortcut(item.key)">
              {{ recordingShortcut === item.key ? '请按键' : shortcutLabel(item.key) }}
            </button>
            <button v-if="shortcutBindings[item.key]" class="shortcut-clear" title="清除快捷键" @click="clearShortcut(item.key)">×</button>
          </div>
        </div>
      </aside>
    </main>

    <div v-if="notice" class="director-notice" :class="notice.ok ? 'success' : 'error'">
      <span class="status-dot" />{{ notice.text }}
    </div>
  </div>
</template>

<style scoped>
.director-page { min-height: 100%; padding: 28px 32px 36px; background: #090b10; color: #f4f4f5; }
.director-header { display: flex; align-items: flex-end; justify-content: space-between; padding-bottom: 18px; border-bottom: 1px solid #27272a; }
.director-kicker, .surface-title small, .safety-head small { color: #71717a; font-size: 10px; font-weight: 800; letter-spacing: 0; }
h1 { margin: 3px 0 0; font-size: 28px; line-height: 1; font-weight: 800; }
.active-output { display: flex; align-items: center; gap: 10px; min-width: 170px; padding: 9px 12px; border-left: 3px solid #22c55e; background: #14171c; }
.active-output.is-hidden { border-color: #ef4444; }
.active-output .status-dot { background: #22c55e; }
.active-output.is-hidden .status-dot { background: #ef4444; }
.active-output div { display: flex; flex-direction: column; }
.active-output small, .connection-cell small, .match-band small { color: #71717a; font-size: 10px; }
.active-output strong { font-size: 14px; }
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex: none; }
.connection-strip { display: grid; grid-template-columns: repeat(4, minmax(135px, 1fr)) auto; min-height: 66px; margin-top: 18px; border: 1px solid #2b2f36; background: #111318; }
.connection-cell { display: flex; align-items: center; gap: 10px; padding: 12px 15px; border-right: 1px solid #2b2f36; }
.connection-cell > div { display: flex; min-width: 0; flex-direction: column; }
.connection-cell strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.connection-cell.ok .status-dot { background: #22c55e; box-shadow: 0 0 10px #22c55e55; }
.connection-cell.warn .status-dot { background: #f59e0b; }
.connection-cell.bad .status-dot { background: #ef4444; }
.connection-cell.idle .status-dot { background: #71717a; }
.check-button { align-self: center; justify-self: center; margin: 0 12px; white-space: nowrap; }
.check-button svg, .refresh-button svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; }
.match-band { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 0; margin-top: 10px; background: #0e1015; border-bottom: 1px solid #27272a; }
.match-band > div:not(.match-error) { display: flex; flex-direction: column; gap: 3px; padding: 11px 15px; border-right: 1px solid #22252b; }
.match-band strong { font-size: 12px; overflow-wrap: anywhere; }
.website-match-controls { display: grid; grid-template-columns: minmax(0, 1fr) 42px 42px; gap: 5px; }
.website-match-controls select, .website-match-controls button { min-width: 0; border: 1px solid #3f3f46; background: #171a20; color: #d4d4d8; font-size: 10px; }
.website-match-controls select { padding: 3px 4px; }
.website-match-controls button { padding: 3px 2px; }
.website-match-controls button:hover:not(:disabled) { cursor: pointer; border-color: #71717a; color: #fff; }
.website-match-controls button:disabled { opacity: .45; }
.match-error { grid-column: 1 / -1; padding: 8px 15px; color: #fca5a5; background: #450a0a55; font-size: 11px; }
.browser-source-band { display: grid; grid-template-columns: minmax(0, 1fr) 90px 90px; gap: 1px; margin-top: 10px; border: 1px solid #2b2f36; background: #2b2f36; }
.browser-source-band > div { display: grid; grid-template-columns: 110px minmax(0, 1fr); align-items: center; min-width: 0; padding: 9px 12px; background: #101217; }
.browser-source-band small { color: #a1a1aa; font-size: 10px; font-weight: 800; }
.browser-source-band input { min-width: 0; border: 0; outline: 0; background: transparent; color: #e4e4e7; font-family: Consolas, monospace; font-size: 11px; }
.browser-source-band button { display: flex; align-items: center; justify-content: center; gap: 7px; border: 0; background: #15181e; color: #d4d4d8; font-size: 11px; font-weight: 700; }
.browser-source-band button:hover { cursor: pointer; background: #22262e; color: #fff; }
.browser-source-band svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.8; }
.director-workspace { display: grid; grid-template-columns: minmax(580px, 1fr) 260px; gap: 18px; margin-top: 22px; }
.control-surface { border: 1px solid #292d34; background: #101217; }
.surface-title { display: flex; align-items: center; justify-content: space-between; padding: 15px 17px; border-bottom: 1px solid #292d34; }
.surface-title h2 { margin: 2px 0 0; font-size: 16px; }
.surface-title > span { color: #a1a1aa; font-size: 11px; }
.scene-row { display: grid; grid-template-columns: 48px minmax(190px, 1fr) 180px 38px; align-items: center; min-height: 78px; padding: 0 14px 0 0; border-bottom: 1px solid #24272d; }
.scene-row:last-child { border-bottom: 0; }
.scene-number { align-self: stretch; display: grid; place-items: center; color: #52525b; background: #0b0d11; font-size: 11px; font-weight: 800; }
.scene-copy { display: flex; flex-direction: column; gap: 3px; padding: 0 16px; min-width: 0; }
.scene-copy strong { font-size: 14px; }
.scene-copy span { color: #71717a; font-size: 11px; }
.scene-button { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; border: 1px solid #3f3f46; background: #22252b; color: #f4f4f5; font-size: 12px; font-weight: 700; transition: background .15s, border-color .15s; }
.scene-button:hover:not(:disabled) { cursor: pointer; border-color: #71717a; background: #30343b; }
.scene-button:disabled { opacity: .45; }
.scene-button svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; }
.scene-button.bp svg { fill: currentColor; stroke: none; }
.scene-button.bp { border-color: #b91c1c; background: #7f1d1d55; }
.scene-button.game { border-color: #0369a1; background: #07598555; }
.scene-button.auto { border-color: #047857; background: #065f4655; }
.scene-button.tactical { border-color: #a16207; background: #713f1255; }
.scene-button.technical { border-color: #b91c1c; background: #7f1d1d55; }
.scene-button.halftime { border-color: #047857; background: #065f4655; }
.scene-button.map-end { border-color: #52525b; }
.scene-button.series-end { border-color: #0e7490; background: #164e6355; }
.split-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.preview-button { width: 32px; height: 32px; margin-left: 6px; display: grid; place-items: center; border: 0; background: transparent; color: #71717a; }
.preview-button:hover { cursor: pointer; color: #e4e4e7; }
.preview-button svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8; }
.safety-panel { height: fit-content; border: 1px solid #292d34; background: #101217; }
.safety-head { display: flex; flex-direction: column; gap: 2px; padding: 15px; border-bottom: 1px solid #292d34; }
.safety-head strong { font-size: 15px; }
.panic-button { display: flex; width: calc(100% - 24px); align-items: center; gap: 12px; margin: 12px; padding: 13px; border: 1px solid #991b1b; background: #450a0a77; color: #fecaca; text-align: left; }
.panic-button:hover:not(:disabled) { cursor: pointer; background: #7f1d1d77; }
.panic-button svg { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 2; }
.panic-button span { display: flex; flex-direction: column; }
.panic-button small { color: #f87171; font-size: 10px; font-weight: 400; }
.safety-list { border-top: 1px solid #292d34; }
.safety-list > div { display: flex; justify-content: space-between; gap: 10px; padding: 10px 13px; border-bottom: 1px solid #24272d; font-size: 11px; }
.safety-list span { color: #71717a; }
.safety-list strong { max-width: 125px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.safety-list .good { color: #6ee7b7; }
.safety-list .muted { color: #71717a; }
.safety-list .warning { color: #fbbf24; }
.upload-toggle { width: calc(100% - 26px); margin: 10px 13px 3px; padding: 8px 10px; border: 1px solid #3f3f46; background: #181b21; color: #d4d4d8; font-size: 11px; font-weight: 700; }
.upload-toggle.enabled { border-color: #166534; color: #bbf7d0; background: #14532d55; }
.upload-toggle:hover { cursor: pointer; border-color: #71717a; }
.refresh-button { width: 100%; justify-content: center; margin: 6px 0; }
.shortcut-panel { border-top: 1px solid #292d34; }
.shortcut-head { border-bottom: 0; padding-bottom: 7px; }
.shortcut-note { margin: 0 13px 8px; color: #71717a; font-size: 10px; line-height: 1.5; }
.shortcut-row { display: grid; grid-template-columns: minmax(0, 1fr) 92px 20px; align-items: center; gap: 5px; padding: 5px 10px 5px 13px; border-top: 1px solid #24272d; color: #d4d4d8; font-size: 11px; }
.shortcut-key { min-height: 25px; overflow: hidden; border: 1px solid #3f3f46; background: #181b21; color: #a1a1aa; font: inherit; text-overflow: ellipsis; white-space: nowrap; }
.shortcut-key:hover, .shortcut-key.recording { cursor: pointer; border-color: #0ea5e9; color: #e0f2fe; background: #082f4955; }
.shortcut-clear { border: 0; background: transparent; color: #71717a; font-size: 17px; line-height: 1; }
.shortcut-clear:hover { cursor: pointer; color: #fca5a5; }
.director-notice { position: fixed; right: 22px; bottom: 20px; z-index: 20; display: flex; align-items: center; gap: 9px; max-width: 460px; padding: 11px 14px; border: 1px solid; background: #111318; font-size: 12px; box-shadow: 0 10px 30px #0008; }
.director-notice.success { border-color: #166534; color: #bbf7d0; }
.director-notice.success .status-dot { background: #22c55e; }
.director-notice.error { border-color: #991b1b; color: #fecaca; }
.director-notice.error .status-dot { background: #ef4444; }
@media (max-width: 1050px) {
  .connection-strip { grid-template-columns: repeat(2, 1fr); }
  .connection-cell:nth-child(2), .connection-cell:nth-child(4) { border-right: 0; }
  .check-button { margin: 10px 12px; justify-self: start; }
  .director-workspace { grid-template-columns: 1fr; }
  .safety-panel { display: grid; grid-template-columns: 180px 1fr; }
  .safety-head { grid-column: 1 / -1; }
}
@media (max-width: 760px) {
  .director-page { padding: 20px 16px; }
  .connection-strip, .match-band { grid-template-columns: 1fr; }
  .browser-source-band { grid-template-columns: 1fr 1fr; }
  .browser-source-band > div { grid-column: 1 / -1; grid-template-columns: 1fr; gap: 5px; }
  .connection-cell { border-right: 0; border-bottom: 1px solid #2b2f36; }
  .scene-row { grid-template-columns: 42px minmax(0, 1fr) 34px; padding-right: 8px; }
  .scene-button, .split-actions { grid-column: 2; margin: 8px 12px 10px; }
  .preview-button { grid-column: 3; grid-row: 1 / span 2; }
  .scene-copy { padding-top: 12px; }
}
</style>
