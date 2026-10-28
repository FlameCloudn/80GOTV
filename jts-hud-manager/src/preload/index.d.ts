import { ElectronAPI } from '@electron-toolkit/preload'

declare global {
  interface Window {
    electron: ElectronAPI
    api: {
      openExternal: (url: string) => Promise<void>
      copyText: (value: string) => Promise<void>
      getAppInfo: () => Promise<{ version: string; gsiPort: number }>
      configureDirectorShortcuts: (bindings: Record<string, string>) => Promise<{ ok: boolean; errors: Record<string, string> }>
      onUpdateAvailable: (callback: (version: string) => void) => void
    }
  }
}
