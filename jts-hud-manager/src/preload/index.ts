import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

const api = {
  // Open a URL in the system browser
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('open-external', url),

  copyText: (value: string): Promise<void> => ipcRenderer.invoke('copy-text', value),

  // 版本号和 CS2 数据端口（底部状态栏用）
  getAppInfo: (): Promise<{ version: string; gsiPort: number }> => ipcRenderer.invoke('app-info'),

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
