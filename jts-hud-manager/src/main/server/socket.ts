import { Server, Socket } from 'socket.io'
import { getDirectorScene, getDirectorVisibility, getHudConfig } from './domains/huds/hud.routes'
import { getActiveHudId } from './server'
import { getLastGSIState } from './integrations/gsi'

export const setupSockets = (io: Server) => {
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
          if (lastState) socket.emit('update', lastState)
        } catch (e) {
          console.error('Failed to push hud_config on register:', e)
        }
      }
    )
  })
}
