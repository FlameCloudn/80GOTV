import { LOCAL_SERVER_URL } from '../index'

// 本地上传的图片（/api/uploads/xxx.png）拼成完整地址；网上的地址原样返回；没有就返回空
export const assetUrl = (value?: string | null): string => {
  const path = String(value || '').trim()
  if (!path) return ''
  if (/^(https?:|data:|blob:)/i.test(path)) return path
  return `${LOCAL_SERVER_URL}${path.startsWith('/') ? '' : '/'}${path}`
}

// de_inferno → Inferno（地图名不翻译）
export const mapLabel = (value?: string | null): string => {
  const name = String(value || '').split('/').pop() || ''
  const clean = name.replace(/^(de|cs|ar|dz)_/i, '')
  return clean ? clean.charAt(0).toUpperCase() + clean.slice(1) : ''
}

// 没有队标时圆圈里写的字：有简称用简称，否则取队名前两个字母
export const teamAbbr = (name?: string | null, shortName?: string | null): string => {
  const short = String(shortName || '').trim()
  if (short) return short.slice(0, 4).toUpperCase()
  const words = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

// bo3 → BO3
export const boLabel = (value?: string | null): string => {
  const found = String(value || '').toUpperCase().match(/BO?([1235])/)
  return found ? `BO${found[1]}` : ''
}

// 秒数 → 04:12
export const formatDuration = (milliseconds: number): string => {
  const total = Math.max(0, Math.floor(milliseconds / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
