import { Request, Response } from 'express'
import { MatchService } from './match.service'

const matchService = new MatchService()

export const getMatches = async (_req: Request, res: Response) => {
  try {
    const matches = await matchService.getAllMatches()
    res.json(matches)
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
}

export const getCurrentMatch = async (_req: Request, res: Response) => {
  try {
    const match = await matchService.getCurrentMatch()
    res.json(match)
  } catch (error: any) {
    res.status(404).json({ error: error.message })
  }
}

export const getMatchById = async (req: Request, res: Response) => {
  try {
    const match = await matchService.getMatchById(req.params.id as string)
    res.json(match)
  } catch (error: any) {
    res.status(404).json({ error: error.message })
  }
}

export const createMatch = async (req: Request, res: Response) => {
  try {
    const match = await matchService.createMatch(req.body)
    res.status(201).json(match)
  } catch (error: any) {
    res.status(400).json({ error: error.message })
  }
}

export const updateMatch = async (req: Request, res: Response) => {
  try {
    const match = await matchService.updateMatch(req.params.id as string, req.body)
    res.json(match)
  } catch (error: any) {
    res.status(400).json({ error: error.message })
  }
}

export const deleteMatch = async (req: Request, res: Response) => {
  try {
    await matchService.deleteMatch(req.params.id as string)
    res.status(204).send()
  } catch (error: any) {
    res.status(500).json({ error: error.message })
  }
}

export const toggleReverseSide = async (req: Request, res: Response) => {
  try {
    const match = await matchService.toggleVetoReverseSide(req.params.mapName as string)
    res.json(match)
  } catch (error: any) {
    res.status(400).json({ error: error.message })
  }
}
