import { Router } from 'express'
import { Server } from 'socket.io'
import { upload } from '../../utils/multer'
import { syncGSITeams } from '../../integrations/gsi'
import {
  getTeams,
  getTeamLogo,
  getTeamById,
  createTeam,
  updateTeam,
  deleteTeam
} from './team.controller'

export default function createTeamRouter(io: Server) {
  const router = Router()

  router.get('/', getTeams)
  router.get('/logo/:id', getTeamLogo) // must be before /:id to avoid conflict
  router.get('/:id', getTeamById)
  router.post('/', upload.single('logo'), createTeam)
  router.put('/:id', upload.single('logo'), async (req, res) => {
    await updateTeam(req, res)
    if (res.statusCode < 400) {
      await syncGSITeams()
      io.emit('match')
    }
  })
  router.delete('/:id', async (req, res) => {
    await deleteTeam(req, res)
    if (res.statusCode < 400) {
      await syncGSITeams()
      io.emit('match')
    }
  })

  return router
}
