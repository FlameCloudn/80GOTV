import { Server, Socket } from 'socket.io'
import { getDirectorScene, getDirectorVisibility, getHudConfig } from './domains/huds/hud.routes'
import { getActiveHudId } from './server'
import { getLastGSIState, getLastGSIStateReceivedAt } from './integrations/gsi'

const GSI_FRESHNESS_INTERVAL_MS = 100

export const createGsiFreshnessPublisher = (
  getReceivedAt: () => number | null,
  emitFreshness: (fresh: boolean) => void,
  now: () => number = Date.now
): (() => void) => {
  let lastFresh: boolean | null = null
  return () => {
    const receivedAt = getReceivedAt()
    const age = receivedAt === null ? Infinity : now() - receivedAt
    const fresh = age >= 0 && age <= 5000
    if (fresh === lastFresh) return
    lastFresh = fresh
    emitFreshness(fresh)
  }
}

export const setupSockets = (io: Server) => {
  const publishFreshness = createGsiFreshnessPublisher(
    getLastGSIStateReceivedAt,
    (fresh) => io.to('huds').emit('hud_action', { action: 'gsiFreshness', data: fresh ? 'fresh' : 'stale' })
  )
  publishFreshness()
  setInterval(publishFreshness, GSI_FRESHNESS_INTERVAL_MS)

  io.on('connection', (socket: Socket) => {
    // HUD registration:
    socket.on('started', () => {
      socket.emit('readyToRegister')
    })

    // HUD emits "register", server pushes the latest saved panel config
    socket.on(
      'register',
      async (hudName: string, _isDev: boolean, _game: string, _type: string) => {
        try {
          // Mark socket as a HUD so GSI updates can be filtered for it
          socket.join('huds')
          const hudId = getActiveHudId() || hudName
          const config = await getHudConfig(hudId)
          socket.emit('hud_config', config)
          socket.emit('hud_action', { action: 'directorScene', data: getDirectorScene(hudId) })
          socket.emit('hud_action', {
            action: 'directorVisibility',
            data: getDirectorVisibility(hudId) ? 'show' : 'hide'
          })
          const lastState = getLastGSIState()
          socket.emit('hud_action', {
            action: 'gsiFreshness',
            data: lastState && getLastGSIStateReceivedAt() !== null ? 'fresh' : 'stale'
          })
          if (lastState) socket.emit('update', lastState)
        } catch (e) {
          console.error('Failed to push hud_config on register:', e)
        }
      }
    )
  })
}
