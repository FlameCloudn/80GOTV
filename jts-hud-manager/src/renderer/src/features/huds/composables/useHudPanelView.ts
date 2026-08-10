import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { API_URL } from '../../../index'
import { useTeams } from '../../teams/composables/useTeams'
import { usePlayers } from '../../players/composables/usePlayers'
import { useMatches } from '../../matches/composables/useMatches'
import { socket } from '../../../socket'

export type PanelInput = {
  type: string
  name: string
  label: string
  default?: any
  values?: { name: string; label: string }[]
}

export type PanelSection = {
  name: string
  label: string
  inputs: PanelInput[]
}

const EMPTY_SECTION: PanelSection = { name: '', label: '', inputs: [] }
const HUD_BASE = API_URL.replace('/api', '')

export function useHudPanelView() {
  const route = useRoute()
  const hudId = route.params.hudId as string

  const { teams, fetchTeams } = useTeams()
  const { players, fetchPlayers } = usePlayers()
  const { matches, fetchMatches } = useMatches()

  const panel = ref<PanelSection[]>([])
  const config = ref<Record<string, Record<string, any>>>({})
  const sectionStatus = ref<Record<string, 'idle' | 'saving' | 'saved' | 'error'>>({})
  const activeTab = ref<string>('')

  const activeSection = computed<PanelSection>(
    () => panel.value.find((s) => s.name === activeTab.value) ?? EMPTY_SECTION
  )

  const hasNonActionInputs = (section: PanelSection) =>
    section.inputs.some((i) => i.type !== 'action')

  const hasPlayerInput = (section: PanelSection) => section.inputs.some((i) => i.type === 'player')

  // --- Live player tracking ---
  const livePlayerSteamIds = ref<Set<string>>(new Set())
  let livePlayerSignature = ''
  const showOnlyActivePlayers = ref<Record<string, boolean>>({})

  const onGSIUpdate = (data: any) => {
    const ids = data?.allplayers ? Object.keys(data.allplayers).sort() : []
    const signature = ids.join('|')
    if (signature === livePlayerSignature) return
    livePlayerSignature = signature
    livePlayerSteamIds.value = new Set(ids)
  }

  const playersForSection = (sectionName: string) => {
    if (!showOnlyActivePlayers.value[sectionName] || livePlayerSteamIds.value.size === 0) {
      return players.value
    }
    return players.value.filter((p) => p.steamid && livePlayerSteamIds.value.has(p.steamid))
  }

  // --- Load ---
  const loadPanel = async () => {
    const res = await fetch(`${API_URL}/huds/${hudId}/panel`)
    if (!res.ok) return
    panel.value = await res.json()
  }

  const loadConfig = async () => {
    const res = await fetch(`${API_URL}/huds/${hudId}/config`)
    if (res.ok) config.value = await res.json()
  }

  const seedConfig = () => {
    for (const section of panel.value) {
      if (!config.value[section.name]) config.value[section.name] = {}
      if (!(section.name in showOnlyActivePlayers.value)) {
        showOnlyActivePlayers.value[section.name] = false
      }
      for (const input of section.inputs) {
        if (input.type === 'action') continue
        const currentValue = config.value[section.name][input.name]
        if (currentValue === undefined || (currentValue === '' && input.default !== undefined)) {
          config.value[section.name][input.name] =
            input.default ?? (input.type === 'checkbox' ? false : input.type === 'images' ? [] : '')
        }
      }
    }
  }

  onMounted(async () => {
    socket.on('update', onGSIUpdate)
    await Promise.all([fetchTeams(), fetchPlayers(), fetchMatches()])
    await loadPanel()
    if (panel.value.length) activeTab.value = panel.value[0].name
    seedConfig()
    await loadConfig()
    seedConfig()
  })

  onUnmounted(() => {
    socket.off('update', onGSIUpdate)
  })

  // --- Save section config ---
  const saveSectionConfig = async (sectionName: string) => {
    sectionStatus.value[sectionName] = 'saving'
    try {
      const res = await fetch(`${API_URL}/huds/${hudId}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config.value)
      })
      sectionStatus.value[sectionName] = res.ok ? 'saved' : 'error'
    } catch {
      sectionStatus.value[sectionName] = 'error'
    } finally {
      setTimeout(() => {
        sectionStatus.value[sectionName] = 'idle'
      }, 2000)
    }
  }

  // --- Fire action ---
  const fireAction = async (actionName: string, valueName: string) => {
    await fetch(`${API_URL}/huds/${hudId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: actionName, data: valueName })
    })
  }

  // --- Image helpers ---
  const uploadFile = async (file: File): Promise<{ url: string; filename: string } | null> => {
    const formData = new FormData()
    formData.append('image', file)
    const res = await fetch(`${API_URL}/huds/${hudId}/upload`, { method: 'POST', body: formData })
    if (!res.ok) return null
    const data = await res.json()
    return { url: `${HUD_BASE}${data.url}`, filename: data.filename }
  }

  const deleteFile = async (filename: string) => {
    await fetch(`${API_URL}/huds/${hudId}/upload/${encodeURIComponent(filename)}`, {
      method: 'DELETE'
    })
  }

  const filenameFromUrl = (url: string) => url.split('/').pop() ?? ''

  const uploadImage = async (sectionName: string, inputName: string, file: File) => {
    const existing = config.value[sectionName]?.[inputName]
    if (existing) await deleteFile(filenameFromUrl(existing))
    const result = await uploadFile(file)
    if (result) {
      if (!config.value[sectionName]) config.value[sectionName] = {}
      config.value[sectionName][inputName] = result.url
    }
  }

  const clearImage = async (sectionName: string, inputName: string) => {
    const existing = config.value[sectionName]?.[inputName]
    if (existing) await deleteFile(filenameFromUrl(existing))
    config.value[sectionName][inputName] = ''
  }

  const uploadImageToList = async (sectionName: string, inputName: string, file: File) => {
    const result = await uploadFile(file)
    if (result) {
      if (!Array.isArray(config.value[sectionName][inputName]))
        config.value[sectionName][inputName] = []
      config.value[sectionName][inputName].push(result.url)
    }
  }

  const removeImageFromList = async (sectionName: string, inputName: string, url: string) => {
    await deleteFile(filenameFromUrl(url))
    config.value[sectionName][inputName] = (
      config.value[sectionName][inputName] as string[]
    ).filter((u) => u !== url)
  }

  return {
    hudId,
    teams,
    players,
    matches,
    panel,
    config,
    sectionStatus,
    activeTab,
    activeSection,
    hasNonActionInputs,
    hasPlayerInput,
    livePlayerSteamIds,
    showOnlyActivePlayers,
    playersForSection,
    saveSectionConfig,
    fireAction,
    uploadImage,
    clearImage,
    uploadImageToList,
    removeImageFromList
  }
}
