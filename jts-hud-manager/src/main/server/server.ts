import dotenv from 'dotenv'
dotenv.config() // Load .env variables before anything else

import './database/sqlite'
import express from 'express'
import cors from 'cors'

import { createServer } from 'http'
import { Server } from 'socket.io'
import { setupSockets } from './socket'
import { setupGSI } from './integrations/gsi'
import { setup80Gotv } from './integrations/80gotv'

import createMatchRouter from './domains/matches/match.routes'
import playerRoutes from './domains/players/player.routes'
import createTeamRouter from './domains/teams/team.routes'
import createHudRouter from './domains/huds/hud.routes'
import settingsRoutes from './domains/settings/settings.routes'
import spectatorRoutes from './domains/spectator/spectator.routes'
import createGameMapRouter from './domains/game-maps/game-maps.routes'
import { uploadsPath } from './utils/multer'
import { getHudsDir, getBuiltinHudDir } from '../paths'
import { signedHudMiddleware } from './middleware/signedHudMiddleware'

// Track the currently active HUD id so the socket register handler can look up correct HUD
let activeHudId: string | null = null
export const setActiveHudId = (id: string | null) => {
  activeHudId = id
}
export const getActiveHudId = () => activeHudId

// Setup HUD Server (Port 1349)
const hudsPath = getHudsDir()
const app = express()
const HUD_PORT = Number(process.env.HUD_PORT ?? 1349)
const GSI_PORT = Number(process.env.GSI_PORT ?? 23415)
const LOCAL_HOST = '127.0.0.1'
const LOCAL_ORIGINS = [`http://${LOCAL_HOST}:${HUD_PORT}`, `http://localhost:${HUD_PORT}`]

const localCorsOrigin = (origin: string | undefined, callback: (error: Error | null, allow?: boolean) => void) => {
  // CS2 and same-origin requests do not send an Origin header. Browser pages
  // must come from this desktop app's loopback port.
  if (!origin || LOCAL_ORIGINS.includes(origin)) return callback(null, true)
  return callback(new Error('外部来源禁止访问导播本地接口'))
}

app.use(
  cors({
    origin: localCorsOrigin,
    methods: ['GET', 'POST', 'PUT', 'DELETE']
  })
)

const httpServer = createServer(app)
export const io = new Server(httpServer, {
  cors: { origin: LOCAL_ORIGINS }
})

app.use(express.json())
// Middleware to handle signed HUD files (decode JWT before serving)
app.use(signedHudMiddleware)
// The default mount must come first so it takes priority over the user huds folder
app.use(
  '/huds/default',
  express.static(getBuiltinHudDir(), {
    etag: false,
    lastModified: false,
    setHeaders: (res) => {
      res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate')
      res.setHeader('Pragma', 'no-cache')
      res.setHeader('Expires', '0')
    }
  })
)
app.use('/huds', express.static(hudsPath))
app.use('/api/uploads', express.static(uploadsPath))

app.use('/api/huds', createHudRouter(io))
app.use('/api/teams', createTeamRouter(io))
app.use('/api/players', playerRoutes)
app.use('/api/match', createMatchRouter(io))
app.use('/api/settings', settingsRoutes)
app.use('/api/spectator', spectatorRoutes)
app.use('/api/game-maps', createGameMapRouter())
app.use('/api/80gotv', setup80Gotv(io))

setupSockets(io)

// Setup GSI Listener Server (Port 23415)
const gsiApp = express()
gsiApp.use(express.json())
gsiApp.use(cors({ origin: localCorsOrigin }))
gsiApp.use('/cs2', setupGSI(io)) // This is what the gsi cfg file sends data to

let serversRunning = false

// Start both servers
export function startServers(): void {
  if (serversRunning) return
  serversRunning = true

  httpServer.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code === 'EADDRINUSE') {
      console.error(`[HUD Server] Port ${HUD_PORT} is already in use.`)
    } else {
      console.error('[HUD Server] Server error:', err)
    }
  })
  httpServer.listen(HUD_PORT, LOCAL_HOST, () => {
    console.log(`HUD Server and WebSockets listening on ${LOCAL_HOST}:${HUD_PORT}`)
  })

  const gsiServer = gsiApp.listen(GSI_PORT, LOCAL_HOST, () => {
    console.log(`CS2 GSI Listener running on ${LOCAL_HOST}:${GSI_PORT}`)
  })
  gsiServer.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code === 'EADDRINUSE') {
      console.error(`[GSI Server] Port ${GSI_PORT} is already in use.`)
    } else {
      console.error('[GSI Server] Server error:', err)
    }
  })

  // Store reference so stopServers/shutdown can close it
  activeGsiServer = gsiServer
}

let activeGsiServer: ReturnType<typeof gsiApp.listen> | null = null

// Stop both servers
export function stopServers(): Promise<void> {
  if (!serversRunning) return Promise.resolve()
  serversRunning = false
  return new Promise((resolve) => {
    const done = () => {
      activeGsiServer = null
      resolve()
    }
    io.close(() => {
      httpServer.closeAllConnections?.()
      httpServer.close(() => {
        if (activeGsiServer) {
          activeGsiServer.closeAllConnections?.()
          activeGsiServer.close(() => {
            console.log('[Server] Servers stopped.')
            done()
          })
        } else {
          done()
        }
      })
    })
  })
}

// Gracefully shut down all servers and socket connections (called on app quit)
export function shutdown(): Promise<void> {
  return stopServers()
}
