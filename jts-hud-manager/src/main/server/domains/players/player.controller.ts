import { Request, Response } from 'express'
import { PlayerService } from './player.service'
import { deleteUploadedFile } from '../../utils/multer'
import { syncCoaches } from '../../integrations/gsi'
import { downloadSteamAvatar, fetchSteamPublicProfile } from './steam-profile.service'

const playerService = new PlayerService()

export const getPlayers = async (req: Request, res: Response) => {
  try {
    const steamids = req.query.steamids as string | undefined
    const players = await playerService.getPlayers(steamids)
    res.json(players)
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
}

export const getPlayerAvatar = async (req: Request, res: Response) => {
  try {
    const avatarData = await playerService.getPlayerAvatar(req.params.steamid as string)
    res.json(avatarData)
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
}

export const getSteamProfile = async (req: Request, res: Response) => {
  try {
    const profile = await fetchSteamPublicProfile(req.params.steamid as string)
    res.json(profile)
  } catch (error: any) {
    const message = error?.message || 'Steam 资料读取失败'
    const status = message.includes('17 位数字') ? 400 : 502
    res.status(status).json({ error: message })
  }
}

export const getPlayerById = async (req: Request, res: Response) => {
  try {
    const player = await playerService.getPlayerById(req.params.id as string)
    if (!player) return res.status(404).json({ error: 'Player not found' })
    res.json(player)
    return
  } catch (error: any) {
    res.status(500).json({ error: error.message })
    return
  }
}

export const createPlayer = async (req: Request, res: Response) => {
  let newAvatar = ''
  try {
    const playerData = { ...req.body }
    const steamAvatarUrl = String(playerData.steamAvatarUrl || '')
    delete playerData.steamAvatarUrl
    if (req.file) {
      newAvatar = `/api/uploads/${req.file.filename}`
      playerData.avatar = newAvatar
    } else if (steamAvatarUrl) {
      newAvatar = await downloadSteamAvatar(String(playerData.steamid || ''), steamAvatarUrl)
      playerData.avatar = newAvatar
    }
    // FormData sends booleans as strings
    playerData.isCoach = playerData.isCoach === 'true' || playerData.isCoach === true
    const player = await playerService.createPlayer(playerData)
    syncCoaches()
    res.status(201).json(player)
  } catch (error: any) {
    if (newAvatar) deleteUploadedFile(newAvatar)
    res.status(400).json({ error: error.message })
  }
}

export const updatePlayer = async (req: Request, res: Response) => {
  let newAvatar = ''
  try {
    const playerData = { ...req.body }
    const steamAvatarUrl = String(playerData.steamAvatarUrl || '')
    delete playerData.steamAvatarUrl
    const existing = await playerService.getPlayerById(req.params.id as string)
    if (!existing) return res.status(404).json({ error: 'Player not found' })
    if (req.file) {
      newAvatar = `/api/uploads/${req.file.filename}`
      playerData.avatar = newAvatar
    } else if (steamAvatarUrl) {
      newAvatar = await downloadSteamAvatar(String(playerData.steamid || ''), steamAvatarUrl)
      playerData.avatar = newAvatar
    }
    // FormData sends booleans as strings
    playerData.isCoach = playerData.isCoach === 'true' || playerData.isCoach === true
    const player = await playerService.updatePlayer(req.params.id as string, playerData)
    if (!player) return res.status(404).json({ error: 'Player not found' })
    if (newAvatar && existing.avatar && existing.avatar !== newAvatar) {
      deleteUploadedFile(existing.avatar)
    }
    syncCoaches()
    res.json(player)
    return
  } catch (error: any) {
    if (newAvatar) deleteUploadedFile(newAvatar)
    res.status(400).json({ error: error.message })
    return
  }
}

export const deletePlayer = async (req: Request, res: Response) => {
  try {
    const player = await playerService.getPlayerById(req.params.id as string)
    if (player?.avatar) deleteUploadedFile(player.avatar)
    await playerService.deletePlayer(req.params.id as string)
    syncCoaches()
    res.status(204).send()
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
}
