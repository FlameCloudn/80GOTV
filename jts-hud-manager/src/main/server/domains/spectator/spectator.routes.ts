import { Router, Request, Response } from 'express'
import { setSpectatorSlots } from '../../integrations/gsi'

const router = Router()

// PUT /api/spectator/slots - update the observer_slot remapping used in GSI payloads
router.put('/slots', (req: Request, res: Response) => {
  const { slots } = req.body as { slots: Record<number, string> }
  if (!slots || typeof slots !== 'object') {
    return res.status(400).json({ error: 'slots object required' })
  }
  setSpectatorSlots(slots)
  return res.json({ ok: true })
})

export default router
