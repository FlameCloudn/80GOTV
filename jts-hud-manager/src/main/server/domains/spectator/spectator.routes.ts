import { Router, Request, Response } from 'express'
import { setSpectatorSlots } from '../../integrations/gsi'
import { dbGet, dbReady, dbRun } from '../../database/sqlite'

const router = Router()
const SETTINGS_KEY = 'spectatorSlots'
type SpectatorSlots = Record<number, string>

const normalizeSlots = (value: unknown): SpectatorSlots | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const input = value as Record<string, unknown>
  return Object.fromEntries(
    Array.from({ length: 10 }, (_, index) => {
      const slot = index + 1
      return [slot, typeof input[slot] === 'string' ? input[slot] : '']
    })
  ) as SpectatorSlots
}

let savedSlots: SpectatorSlots | null = null
const restoreSavedSlots = async (): Promise<SpectatorSlots | null> => {
  await dbReady
  const row = await dbGet('SELECT value FROM settings WHERE key = ?', [SETTINGS_KEY])
  if (typeof row?.value !== 'string') return null
  try {
    return normalizeSlots(JSON.parse(row.value))
  } catch {
    return null
  }
}

const slotsReady = restoreSavedSlots()
  .then((slots) => {
    savedSlots = slots
    if (slots) setSpectatorSlots(slots)
    return slots
  })
  .catch((error) => {
    console.error('[Spectator] Failed to restore saved slots:', error)
    return null
  })

// PUT /api/spectator/slots - update the observer_slot remapping used in GSI payloads
router.get('/slots', async (_req: Request, res: Response) => {
  try {
    await slotsReady
    return res.json({ slots: savedSlots })
  } catch (error: any) {
    return res.status(500).json({ error: error.message })
  }
})

router.put('/slots', async (req: Request, res: Response) => {
  const slots = normalizeSlots(req.body?.slots)
  if (!slots) {
    return res.status(400).json({ error: 'slots object required' })
  }
  try {
    await slotsReady
    await dbReady
    await dbRun(
      'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
      [SETTINGS_KEY, JSON.stringify(slots)]
    )
    savedSlots = slots
    setSpectatorSlots(slots)
    return res.json({ ok: true, slots })
  } catch (error: any) {
    return res.status(500).json({ error: error.message })
  }
})

export default router
