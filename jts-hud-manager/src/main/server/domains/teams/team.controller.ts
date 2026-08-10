import path from 'path'
import { Request, Response } from 'express'
import { TeamService } from './team.service'
import { uploadsPath, deleteUploadedFile } from '../../utils/multer'
import { PlayerRepository } from '../players/player.repository'

const teamService = new TeamService()
const playerRepo = new PlayerRepository()

export const getTeamLogo = async (req: Request, res: Response) => {
  try {
    const filename = await teamService.getTeamLogoPath(req.params.id as string)
    if (!filename) return res.status(404).json({ error: 'Logo not found' })
    res.sendFile(path.join(uploadsPath, filename))
    return
  } catch (error: any) {
    res.status(500).json({ error: error.message })
    return
  }
}

export const getTeams = async (_req: Request, res: Response) => {
  try {
    const teams = await teamService.getTeams()
    res.json(teams)
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
}

export const getTeamById = async (req: Request, res: Response) => {
  try {
    const team = await teamService.getTeamById(req.params.id as string)
    if (!team) return res.status(404).json({ error: 'Team not found' })
    res.json(team)
    return
  } catch (error: any) {
    res.status(500).json({ error: error.message })
    return
  }
}

export const createTeam = async (req: Request, res: Response) => {
  try {
    const teamData = req.body
    if (req.file) {
      teamData.logo = `/api/uploads/${req.file.filename}`
    }
    const team = await teamService.createTeam(teamData)
    res.status(201).json(team)
  } catch (error: any) {
    res.status(400).json({ error: error.message })
  }
}

export const updateTeam = async (req: Request, res: Response) => {
  try {
    const { playerIds: rawPlayerIds, ...teamData } = req.body
    if (req.file) {
      // New logo uploaded — delete the old one first
      const existing = await teamService.getTeamById(req.params.id as string)
      if (existing?.logo) deleteUploadedFile(existing.logo)
      teamData.logo = `/api/uploads/${req.file.filename}`
    }
    const team = await teamService.updateTeam(req.params.id as string, teamData)
    if (!team) return res.status(404).json({ error: 'Team not found' })

    if (rawPlayerIds !== undefined) {
      const playerIds = Array.isArray(rawPlayerIds) ? rawPlayerIds : JSON.parse(rawPlayerIds)
      if (!Array.isArray(playerIds) || !playerIds.every((id) => typeof id === 'string')) {
        return res.status(400).json({ error: 'playerIds must be an array of player IDs' })
      }
      await teamService.setTeamPlayers(req.params.id as string, playerIds)
    }

    res.json(team)
    return
  } catch (error: any) {
    res.status(400).json({ error: error.message })
    return
  }
}

export const deleteTeam = async (req: Request, res: Response) => {
  try {
    const team = await teamService.getTeamById(req.params.id as string)
    if (team?.logo) deleteUploadedFile(team.logo)

    if (req.query.deletePlayers === 'true') {
      // Also delete every player avatar for this team
      const players = await playerRepo.getPlayers()
      for (const p of players.filter((p) => p.team === req.params.id)) {
        if (p.avatar) deleteUploadedFile(p.avatar)
      }
      await teamService.deleteTeamWithPlayers(req.params.id as string)
    } else {
      await teamService.deleteTeam(req.params.id as string)
    }
    res.status(204).send()
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
}
