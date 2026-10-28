import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { API_URL, LOCAL_SERVER_URL } from '../../../index'
import { refreshStatus, sendDirectorCommand, useDirectorStatus } from '../../../composables/useDirectorStatus'
import { logActivity } from '../../../composables/useActivityLog'
import { errorText, showToast } from '../../../composables/useToasts'

export type WebsiteMatchOption = { key: string; label: string; source_type?: string }

const AUTO_SYNC_DELAY_MS = 1500
const MATCH_LIST_REFRESH_MS = 30000
const BP_FLASH_MS = 1500

// 出错：右上角提示（不自动消失）+ 记进“最近操作”
const fail = (key: string, error: unknown): void => {
  const text = errorText(error)
  showToast(text, 'error', { key })
  logActivity(text, 'bad')
}

const postJson = async (path: string, body: unknown, fallbackError: string) => {
  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || !payload.ok) throw new Error(payload.error || fallbackError)
  return payload
}

// 场景按钮：切换、展示 BP、全部隐藏
function useSceneCommands() {
  const commandBusy = ref(false)
  const bpFlashUntil = ref(0)

  const run = async (command: string, doneText: string) => {
    commandBusy.value = true
    try {
      const result = await sendDirectorCommand(command)
      if (command === 'hide_all' || command === 'hide') {
        if (result.delivery === 'pending') {
          logActivity('已保存隐藏目标；当前没有 HUD 连接，连接后会应用', 'warn')
        } else {
          logActivity(`已发送隐藏指令给 ${result.hudClients || 0} 个 HUD 连接；未确认 OBS 已显示`)
        }
      } else {
        logActivity(doneText)
      }
      if (command === 'bp') bpFlashUntil.value = Date.now() + BP_FLASH_MS
    } catch (error) {
      fail('director-command', error)
    } finally {
      commandBusy.value = false
      await refreshStatus()
    }
  }
  return { commandBusy, bpFlashUntil, run }
}

// 网站比赛列表：每 30 秒读一次；没手动选过时自动跟随第一场并自动同步（和旧版一样）
function useWebsiteMatches() {
  const { selectedMatch } = useDirectorStatus()
  const websiteMatches = ref<WebsiteMatchOption[]>([])
  const selectedWebsiteMatch = ref('')
  const userSelectedMatch = ref(false)
  const lastAutoSyncKey = ref('')
  const listBusy = ref(false)
  const syncBusy = ref(false)
  let autoSyncTimer: ReturnType<typeof setTimeout> | null = null

  const syncWebsiteMatch = async () => {
    if (!selectedWebsiteMatch.value) return
    syncBusy.value = true
    try {
      const payload = await postJson('/80gotv/sync', { matchId: selectedWebsiteMatch.value }, '同步比赛资料失败')
      lastAutoSyncKey.value = selectedWebsiteMatch.value
      logActivity(`已同步：${payload.summary || selectedWebsiteMatch.value}`)
      await refreshStatus()
    } catch (error) {
      fail('website-sync', error)
    } finally {
      syncBusy.value = false
    }
  }

  // 没手动选过：跟随网站列表第一场；手动选过：保留手动选的，那场不在列表里了才退回已同步的那场
  const pickWebsiteMatch = (keys: string[]): string => {
    if (!userSelectedMatch.value) return keys[0] || ''
    if (keys.includes(selectedWebsiteMatch.value)) return selectedWebsiteMatch.value
    const synced = selectedMatch.value
    return synced && keys.includes(synced) ? synced : keys[0] || ''
  }

  const scheduleAutoSync = (key: string) => {
    if (userSelectedMatch.value || !key || key === lastAutoSyncKey.value) return
    lastAutoSyncKey.value = key
    if (autoSyncTimer) clearTimeout(autoSyncTimer)
    autoSyncTimer = setTimeout(() => {
      if (selectedWebsiteMatch.value === key && !syncBusy.value) void syncWebsiteMatch()
    }, AUTO_SYNC_DELAY_MS)
  }

  const loadWebsiteMatches = async () => {
    listBusy.value = true
    try {
      const response = await fetch(`${API_URL}/80gotv/matches`)
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || !payload.ok) throw new Error(payload.error || '读取网站比赛失败')
      const sources: WebsiteMatchOption[] = payload.sources || payload.matches || []
      websiteMatches.value = sources
      selectedWebsiteMatch.value = pickWebsiteMatch(sources.map((source) => source.key))
      scheduleAutoSync(selectedWebsiteMatch.value)
    } catch (error) {
      fail('website-matches', error)
    } finally {
      listBusy.value = false
    }
  }

  const chooseWebsiteMatch = (key: string) => {
    selectedWebsiteMatch.value = key
    userSelectedMatch.value = true
  }
  const stopAutoSync = () => autoSyncTimer && clearTimeout(autoSyncTimer)

  return {
    websiteMatches, selectedWebsiteMatch, listBusy, syncBusy,
    loadWebsiteMatches, syncWebsiteMatch, chooseWebsiteMatch, stopAutoSync
  }
}

// 网站实时上传开关、完整连接检查
function useWebsiteLink() {
  const { integration, selectedMatch } = useDirectorStatus()
  const connectionBusy = ref(false)

  const toggleForwardLive = async () => {
    const turnOn = !integration.value?.forwardLiveData
    try {
      const response = await fetch(`${API_URL}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ forwardLiveData: turnOn })
      })
      if (!response.ok) throw new Error('实时上传设置保存失败')
      logActivity(turnOn ? '已开启网站实时上传' : '已停止网站实时上传')
      await refreshStatus()
    } catch (error) {
      fail('website-forward', error)
    }
  }

  const testConnection = async () => {
    connectionBusy.value = true
    try {
      const payload = await postJson('/80gotv/connection-test', { matchId: selectedMatch.value }, '连接检查失败')
      const connection = payload.connection || {}
      const teams = connection.team1_name && connection.team2_name ? ` · ${connection.team1_name} vs ${connection.team2_name}` : ''
      logActivity(`网站已确认比赛 #${connection.match_id || selectedMatch.value}${teams}`)
    } catch (error) {
      fail('website-check', error)
    } finally {
      connectionBusy.value = false
      await refreshStatus()
    }
  }
  return { connectionBusy, toggleForwardLive, testConnection }
}

// OBS 浏览器源地址：复制、在浏览器里预览
function useObsSource() {
  const browserSourceUrl = computed(() => `${LOCAL_SERVER_URL}/huds/default/index.html?isProd=1&v=80gotv-cn-obs-11`)

  const copyBrowserSource = async () => {
    try {
      if (window.api?.copyText) await window.api.copyText(browserSourceUrl.value)
      else await navigator.clipboard.writeText(browserSourceUrl.value)
      showToast('OBS 浏览器源地址已复制', 'success', { key: 'obs-copy' })
    } catch (error) {
      fail('obs-copy', error)
    }
  }

  const openPreview = (query = '') => {
    const params = new URLSearchParams(query)
    params.set('isProd', '1')
    const url = `${LOCAL_SERVER_URL}/huds/default/index.html?${params.toString()}`
    if (window.api?.openExternal) void window.api.openExternal(url)
    else window.open(url, '_blank')
  }
  return { browserSourceUrl, copyBrowserSource, openPreview }
}

export function useDirectorActions() {
  const scenes = useSceneCommands()
  const matches = useWebsiteMatches()
  const link = useWebsiteLink()
  const obs = useObsSource()
  let matchListTimer: ReturnType<typeof setInterval> | null = null

  onMounted(() => {
    void matches.loadWebsiteMatches()
    matchListTimer = setInterval(matches.loadWebsiteMatches, MATCH_LIST_REFRESH_MS)
  })
  onBeforeUnmount(() => {
    if (matchListTimer) clearInterval(matchListTimer)
    matches.stopAutoSync()
  })

  return { ...scenes, ...matches, ...link, ...obs }
}
