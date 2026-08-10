import { Router, Request, Response } from 'express'
import { Server } from 'socket.io'
import {
  getMatches,
  getCurrentMatch,
  getMatchById,
  createMatch,
  updateMatch,
  deleteMatch,
  toggleReverseSide
} from './match.controller'
import { MatchService } from './match.service'
import { syncGSITeams } from '../../integrations/gsi'

const matchService = new MatchService()

export default function createMatchRouter(io: Server) {
  const router = Router()

  router.get('/', getMatches)
  router.get('/current', getCurrentMatch)
  router.get('/:id', getMatchById)

  // Emit 'match' when a new match is created as current
  router.post('/', async (req: Request, res: Response) => {
    await createMatch(req, res)
    if (req.body?.current) {
      io.emit('match')
      syncGSITeams()
    }
  })

  // Emit 'match' if the updated match is or becomes current
  router.put('/:id', async (req: Request, res: Response) => {
    let wasCurrent = false
    try {
      const match = await matchService.getMatchById(req.params.id as string)
      wasCurrent = match.current
    } catch {
      /* match not found, proceed */
    }

    await updateMatch(req, res)
    if ((wasCurrent || req.body?.current) && res.statusCode < 400) {
      io.emit('match')
      syncGSITeams()
    }
  })

  // Emit 'match' if the deleted match was the current one
  router.delete('/:id', async (req: Request, res: Response) => {
    let wasCurrent = false
    try {
      const match = await matchService.getMatchById(req.params.id as string)
      wasCurrent = match.current
    } catch {
      /* match not found, proceed */
    }

    await deleteMatch(req, res)
    if (wasCurrent && res.statusCode < 400) {
      io.emit('match')
      syncGSITeams()
    }
  })

  // Toggle reverseSide on a specific map veto in the current match, then notify HUDs
  router.patch('/current/veto/:mapName/reverse-side', async (req: Request, res: Response) => {
    await toggleReverseSide(req, res)
    if (res.statusCode < 400) {
      io.emit('match')
      syncGSITeams()
    }
  })

  return router
}
