import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

const api = {
  // Open a URL in the system browser
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('open-external', url),

  copyText: (value: string): Promise<void> => ipcRenderer.invoke('copy-text', value),

  configureDirectorShortcuts: (bindings: Record<string, string>) =>
    ipcRenderer.invoke('configure-director-shortcuts', bindings),

  // Listen for update-available notifications from the main process
  onUpdateAvailable: (callback: (version: string) => void): void => {
    ipcRenderer.on('update-available', (_event, version) => callback(version))
  }
}

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI
  // @ts-ignore (define in dts)
  window.api = api
}
