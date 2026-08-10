import * as XLSX from 'xlsx'
import { API_URL } from '../index'

// --- Column Definitions ---

const PLAYER_COLUMNS = [
  { header: '游戏昵称', aliases: ['Username'], key: 'username' },
  { header: '名字', aliases: ['First Name'], key: 'firstName' },
  { header: '姓氏', aliases: ['Last Name'], key: 'lastName' },
  { header: 'Steam ID 64', aliases: ['SteamID64'], key: 'steamid' },
  { header: '国家代码 (ISO)', aliases: ['Country (ISO)'], key: 'country' }
]

const TEAM_COLUMNS = [
  { header: '战队名称', aliases: ['Team Name'], key: 'name' },
  { header: '战队简称', aliases: ['Short Name'], key: 'shortName' },
  { header: '国家代码 (ISO)', aliases: ['Country (ISO)'], key: 'country' }
]

// --- Generic Helpers ---

const downloadWorkbook = (wb: XLSX.WorkBook, filename: string) => {
  XLSX.writeFile(wb, filename)
}

const rowsFromSheet = (file: File): Promise<Record<string, string>[]> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target!.result as ArrayBuffer)
        const wb = XLSX.read(data, { type: 'array' })
        const sheet = wb.Sheets[wb.SheetNames[0]]
        resolve(XLSX.utils.sheet_to_json(sheet, { defval: '' }) as Record<string, string>[])
      } catch (err) {
        reject(err)
      }
    }
    reader.onerror = reject
    reader.readAsArrayBuffer(file)
  })
}

const pickFile = (accept = '.xlsx,.xls,.csv'): Promise<File | null> => {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = accept
    input.onchange = () => resolve(input.files?.[0] ?? null)
    input.oncancel = () => resolve(null)
    input.click()
  })
}

// --- Player Excel ---

export function usePlayerExcel(onComplete: () => Promise<void>) {
  const exportPlayers = (players: any[]) => {
    const rows = players.map((p) =>
      Object.fromEntries(PLAYER_COLUMNS.map(({ header, key }) => [header, p[key] ?? '']))
    )
    const ws = XLSX.utils.json_to_sheet(rows)
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, '选手')
    downloadWorkbook(wb, '选手名单.xlsx')
  }

  const importPlayers = async () => {
    const file = await pickFile()
    if (!file) return

    const rows = await rowsFromSheet(file)
    let imported = 0

    for (const row of rows) {
      const payload: Record<string, string> = {}
      for (const { header, aliases, key } of PLAYER_COLUMNS) {
        const sourceHeader = [header, ...aliases].find((name) => row[name] !== undefined)
        payload[key] = String(sourceHeader ? row[sourceHeader] : '')
      }
      if (!payload.username && !payload.steamid) continue // skip blank rows

      const formData = new FormData()
      Object.entries(payload).forEach(([k, v]) => formData.append(k, v))

      const res = await fetch(`${API_URL}/players`, { method: 'POST', body: formData })
      if (res.ok) imported++
    }

    await onComplete()
    alert(`成功导入 ${imported} 名选手。`)
  }

  return { exportPlayers, importPlayers }
}

// --- Team Excel ---

export function useTeamExcel(onComplete: () => Promise<void>) {
  const exportTeams = (teams: any[]) => {
    const rows = teams.map((t) =>
      Object.fromEntries(TEAM_COLUMNS.map(({ header, key }) => [header, t[key] ?? '']))
    )
    const ws = XLSX.utils.json_to_sheet(rows)
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, '战队')
    downloadWorkbook(wb, '战队名单.xlsx')
  }

  const importTeams = async () => {
    const file = await pickFile()
    if (!file) return

    const rows = await rowsFromSheet(file)
    let imported = 0

    for (const row of rows) {
      const payload: Record<string, string> = {}
      for (const { header, aliases, key } of TEAM_COLUMNS) {
        const sourceHeader = [header, ...aliases].find((name) => row[name] !== undefined)
        payload[key] = String(sourceHeader ? row[sourceHeader] : '')
      }
      if (!payload.name) continue // skip blank rows

      const res = await fetch(`${API_URL}/teams`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (res.ok) imported++
    }

    await onComplete()
    alert(`成功导入 ${imported} 支战队。`)
  }

  return { exportTeams, importTeams }
}
