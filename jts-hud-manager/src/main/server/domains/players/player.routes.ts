// src/main/domains/players/player.routes.ts
import { Router } from 'express'
import { upload } from '../../utils/multer'
import {
  getPlayers,
  getPlayerAvatar,
  getPlayerById,
  getSteamProfile,
  createPlayer,
  updatePlayer,
  deletePlayer
} from './player.controller'

const router = Router()

router.get('/', getPlayers)
router.get('/steam-profile/:steamid', getSteamProfile)
router.get('/avatar/steamid/:steamid', getPlayerAvatar)
router.get('/:id', getPlayerById)
router.post('/', upload.single('avatar'), createPlayer)
router.put('/:id', upload.single('avatar'), updatePlayer)
router.delete('/:id', deletePlayer)

export default router
