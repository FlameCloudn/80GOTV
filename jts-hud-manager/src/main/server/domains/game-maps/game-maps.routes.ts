import { Router, Request, Response } from 'express'
import fs from 'fs'
import path from 'path'
import { app } from 'electron'

type SupportedMap = {
  id: string
  name: string
  originX: number
  originY: number
  pxPerUnit: number
  floors?: { name: string; min_z: number; max_z: number }[]
}

const RADAR_SIZE = 1024

// These values come from the bundled CS2 radar metadata. The HUD projects
// world X/Y coordinates onto the top-left based radar image.
const fallbackMaps: SupportedMap[] = [
  { id: 'de_ancient', name: 'Ancient', originX: 2590 / 4.26, originY: RADAR_SIZE - 2520 / 4.26, pxPerUnit: 1 / 4.26 },
  { id: 'de_anubis', name: 'Anubis', originX: 2830 / 5.25, originY: RADAR_SIZE - 2030 / 5.25, pxPerUnit: 1 / 5.25 },
  { id: 'de_dust2', name: 'Dust II', originX: 2470 / 4.4, originY: RADAR_SIZE - 1255 / 4.4, pxPerUnit: 1 / 4.4 },
  { id: 'de_inferno', name: 'Inferno', originX: 2090 / 4.91, originY: RADAR_SIZE - 1150 / 4.91, pxPerUnit: 1 / 4.91 },
  { id: 'de_mirage', name: 'Mirage', originX: 3240 / 5.02, originY: RADAR_SIZE - 3410 / 5.02, pxPerUnit: 1 / 5.02 },
  { id: 'de_nuke', name: 'Nuke', originX: 3290 / 6.98, originY: RADAR_SIZE - 5990 / 6.98, pxPerUnit: 1 / 6.98 },
  { id: 'de_cache', name: 'Cache', originX: 2020 / 5.54, originY: RADAR_SIZE - 2390 / 5.54, pxPerUnit: 1 / 5.54 }
]

const mapNames: Record<string, string> = {
  ancient: 'Ancient', anubis: 'Anubis', cache: 'Cache', dust2: 'Dust II',
  inferno: 'Inferno', mirage: 'Mirage', nuke: 'Nuke', overpass: 'Overpass',
  train: 'Train', vertigo: 'Vertigo'
}

const loadSupportedMaps = (): SupportedMap[] => {
  try {
    const metadataPath = path.join(app.getAppPath(), 'resources', 'map-radars', 'map-metadata.json')
    const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf-8'))
    const maps = metadata.maps || {}
    const loaded = Object.entries(maps).map(([key, value]: [string, any]) => ({
      id: `de_${key}`,
      name: mapNames[key] || key,
      originX: Number(value.offset?.x || 0) / Number(value.resolution),
      originY: RADAR_SIZE - Number(value.offset?.y || 0) / Number(value.resolution),
      pxPerUnit: 1 / Number(value.resolution),
      floors: value.floors || []
    }))
    return loaded.length ? loaded : fallbackMaps
  } catch {
    return fallbackMaps
  }
}

const getRadarDir = (): string => path.join(app.getAppPath(), 'resources', 'map-radars')

const createGameMapRouter = () => {
  const router = Router()

  router.get('/cs2', (_req: Request, res: Response) => {
    const supportedMaps = loadSupportedMaps()
    res.json(
      supportedMaps.map((map) => ({
        _id: map.id,
        name: map.name,
        lhmId: map.id,
        game: 'cs2',
        inVetoPool: true,
        isActive: true,
        radars: [
          ...(map.floors?.length
            ? map.floors.map((floor, index) => ({
              id: index + 1,
              lhmId: floor.name || `floor${index + 1}`,
              originX: map.originX,
              originY: map.originY,
              pxPerUX: map.pxPerUnit,
              pxPerUY: -map.pxPerUnit,
              radar: floor.name === 'lower' ? 'radar_lower' : 'radar',
              visibleOverHeight: floor.max_z,
              visibleUnderHeight: floor.min_z
            }))
            : [{
              id: 1,
              lhmId: 'default',
              originX: map.originX,
              originY: map.originY,
              pxPerUX: map.pxPerUnit,
              pxPerUY: -map.pxPerUnit,
              radar: 'radar',
              visibleOverHeight: null,
              visibleUnderHeight: null
            }])
        ]
      }))
    )
  })

  router.get('/cs2/image/:mapId/:radarName', (req: Request, res: Response) => {
    const supportedMaps = loadSupportedMaps()
    const map = supportedMaps.find((entry) => entry.id === req.params.mapId)
    if (!map) return res.status(404).json({ error: 'Unsupported map' })
    const radarName = String(req.params.radarName || 'radar')
    if (radarName !== 'radar' && radarName !== 'radar_lower') {
      return res.status(404).json({ error: 'Unsupported radar' })
    }
    const suffix = radarName === 'radar_lower' ? '_lower' : ''
    const radarPath = path.join(getRadarDir(), `${map.id}${suffix}.png`)
    if (!fs.existsSync(radarPath)) return res.status(404).json({ error: 'Radar image is unavailable' })

    return res.sendFile(radarPath)
  })

  return router
}

export default createGameMapRouter
