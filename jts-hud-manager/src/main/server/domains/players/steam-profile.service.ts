import crypto from 'crypto'
import fs from 'fs'
import path from 'path'
import { DOMParser } from '@xmldom/xmldom'
import { uploadsPath } from '../../utils/multer'

export interface SteamPublicProfile {
  steamid: string
  username: string
  avatarUrl: string
}

const MAX_PROFILE_BYTES = 256 * 1024
const MAX_AVATAR_BYTES = 2 * 1024 * 1024
const ALLOWED_AVATAR_HOSTS = ['steamstatic.com', 'akamaihd.net']

const isSteamId64 = (value: string): boolean => /^\d{17}$/.test(value)

const readXmlText = (document: Document, tagName: string): string => {
  return document.getElementsByTagName(tagName)[0]?.textContent?.trim() || ''
}

const isAllowedAvatarUrl = (value: string): boolean => {
  try {
    const url = new URL(value)
    const hostname = url.hostname.toLowerCase()
    return (
      url.protocol === 'https:' &&
      ALLOWED_AVATAR_HOSTS.some((host) => hostname === host || hostname.endsWith(`.${host}`))
    )
  } catch {
    return false
  }
}

const imageExtension = (data: Buffer, contentType: string): string | null => {
  if (data.subarray(0, 3).equals(Buffer.from([0xff, 0xd8, 0xff]))) return 'jpg'
  if (data.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    return 'png'
  }
  if (
    data.subarray(0, 4).toString('ascii') === 'RIFF' &&
    data.subarray(8, 12).toString('ascii') === 'WEBP'
  ) {
    return 'webp'
  }
  if (contentType.includes('jpeg')) return 'jpg'
  if (contentType.includes('png')) return 'png'
  if (contentType.includes('webp')) return 'webp'
  return null
}

export async function fetchSteamPublicProfile(rawSteamId: string): Promise<SteamPublicProfile> {
  const steamid = String(rawSteamId || '').trim()
  if (!isSteamId64(steamid)) {
    throw new Error('Steam64 ID 必须是 17 位数字')
  }

  let response: globalThis.Response
  try {
    response = await fetch(`https://steamcommunity.com/profiles/${steamid}/?xml=1`, {
      headers: { 'User-Agent': 'JTs-Hud-Manager-CN/7.13.26' },
      signal: AbortSignal.timeout(5000)
    })
  } catch {
    throw new Error('无法连接 Steam，请检查网络后重试')
  }

  if (!response.ok) {
    throw new Error(`Steam 返回了错误（${response.status}）`)
  }

  const xml = await response.text()
  if (Buffer.byteLength(xml, 'utf8') > MAX_PROFILE_BYTES) {
    throw new Error('Steam 返回的资料过大，已停止读取')
  }

  const document = new DOMParser().parseFromString(xml, 'text/xml')
  const username = readXmlText(document, 'steamID')
  const profileSteamId = readXmlText(document, 'steamID64')
  const avatarUrl = readXmlText(document, 'avatarFull') || readXmlText(document, 'avatarMedium')
  const steamError = readXmlText(document, 'error')

  if (steamError || !username || (profileSteamId && profileSteamId !== steamid)) {
    throw new Error(steamError || '没有找到这个 Steam64 ID 的公开资料')
  }

  return {
    steamid,
    username,
    avatarUrl: isAllowedAvatarUrl(avatarUrl) ? avatarUrl : ''
  }
}

export async function downloadSteamAvatar(rawSteamId: string, avatarUrl: string): Promise<string> {
  const steamid = String(rawSteamId || '').trim()
  if (!isSteamId64(steamid) || !isAllowedAvatarUrl(avatarUrl)) {
    throw new Error('Steam 头像地址无效')
  }

  let response: globalThis.Response
  try {
    response = await fetch(avatarUrl, {
      headers: { 'User-Agent': 'JTs-Hud-Manager-CN/7.13.26' },
      signal: AbortSignal.timeout(5000)
    })
  } catch {
    throw new Error('Steam 头像下载失败，请稍后重试')
  }

  if (!response.ok || !isAllowedAvatarUrl(response.url)) {
    throw new Error('Steam 头像下载失败')
  }

  const declaredLength = Number(response.headers.get('content-length') || 0)
  if (declaredLength > MAX_AVATAR_BYTES) {
    throw new Error('Steam 头像文件过大')
  }

  const data = Buffer.from(await response.arrayBuffer())
  if (!data.length || data.length > MAX_AVATAR_BYTES) {
    throw new Error('Steam 头像文件无效')
  }

  const extension = imageExtension(data, response.headers.get('content-type') || '')
  if (!extension) {
    throw new Error('Steam 头像格式不受支持')
  }

  const filename = `steam-${steamid}-${Date.now()}-${crypto.randomBytes(5).toString('hex')}.${extension}`
  await fs.promises.writeFile(path.join(uploadsPath, filename), data, { flag: 'wx' })
  return `/api/uploads/${filename}`
}
