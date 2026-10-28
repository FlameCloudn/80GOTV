import { Router, Request, Response } from 'express'
import fs from 'fs'
import path from 'path'
import { app } from 'electron'
import {
  fallbackMaps,
  mapsFromMetadata,
  mapsResponse,
  radarImageFile,
  type SupportedMap
} from './game-maps.config'

const loadSupportedMaps = (): SupportedMap[] => {
  try {
    const metadataPath = path.join(app.getAppPath(), 'resources', 'map-radars', 'map-metadata.json')
    const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf-8'))
    const loaded = mapsFromMetadata(metadata)
    return loaded.length ? loaded : fallbackMaps
  } catch {
    return fallbackMaps
  }
}

const getRadarDir = (): string => path.join(app.getAppPath(), 'resources', 'map-radars')

const createGameMapRouter = () => {
  const router = Router()

  router.get('/cs2', (_req: Request, res: Response) => {
    res.json(mapsResponse(loadSupportedMaps()))
  })

  router.get('/cs2/image/:mapId/:radarName', (req: Request, res: Response) => {
    const supportedMaps = loadSupportedMaps()
    const map = supportedMaps.find((entry) => entry.id === req.params.mapId)
    if (!map) return res.status(404).json({ error: 'Unsupported map' })
    const radarName = String(req.params.radarName || 'radar')
    if (radarName !== 'radar' && radarName !== 'radar_lower') {
      return res.status(404).json({ error: 'Unsupported radar' })
    }
    const imageFile = radarImageFile(map, radarName)
    if (!imageFile) return res.status(404).json({ error: 'Radar image is unavailable' })
    const radarPath = path.join(getRadarDir(), imageFile)
    if (!fs.existsSync(radarPath)) return res.status(404).json({ error: 'Radar image is unavailable' })

    return res.sendFile(radarPath)
  })

  return router
}

export default createGameMapRouter
