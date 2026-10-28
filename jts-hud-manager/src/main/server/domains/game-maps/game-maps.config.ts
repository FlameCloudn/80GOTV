export const RADAR_SIZE = 1024

export type RadarTransform = {
  originX: number
  originY: number
  pxPerUX: number
  pxPerUY: number
}

export type SupportedMapFloor = {
  name: string
  min_z: number
  max_z: number
  transform: RadarTransform
  imageFile?: string
}

export type SupportedMap = {
  id: string
  name: string
  transform: RadarTransform
  imageFile?: string
  floors: SupportedMapFloor[]
}

const mapNames: Record<string, string> = {
  ancient: 'Ancient', anubis: 'Anubis', cache: 'Cache', dust2: 'Dust II',
  inferno: 'Inferno', mirage: 'Mirage', nuke: 'Nuke', overpass: 'Overpass',
  train: 'Train', vertigo: 'Vertigo'
}

const legacyTransform = (resolution: number, offsetX: number, offsetY: number): RadarTransform => ({
  originX: offsetX / resolution,
  originY: RADAR_SIZE - offsetY / resolution,
  pxPerUX: 1 / resolution,
  pxPerUY: -1 / resolution
})

const transformFromMetadata = (value: any): RadarTransform => {
  if (value?.transform) {
    const transform = value.transform
    const result = {
      originX: Number(transform.originX),
      originY: Number(transform.originY),
      pxPerUX: Number(transform.pxPerUX),
      pxPerUY: Number(transform.pxPerUY)
    }
    if (Object.values(result).every(Number.isFinite)) return result
    throw new Error('地图坐标变换不完整')
  }

  const resolution = Number(value?.resolution)
  const offsetX = Number(value?.offset?.x)
  const offsetY = Number(value?.offset?.y)
  if (!Number.isFinite(resolution) || resolution <= 0 || !Number.isFinite(offsetX) || !Number.isFinite(offsetY)) {
    throw new Error('地图比例或原点数据不完整')
  }
  return legacyTransform(resolution, offsetX, offsetY)
}

const safeImageFile = (value: unknown): string | undefined => {
  if (typeof value !== 'string' || !/^[a-z0-9_-]+\.png$/i.test(value)) return undefined
  return value
}

export const mapsFromMetadata = (metadata: any): SupportedMap[] => {
  const entries = metadata?.maps && typeof metadata.maps === 'object'
    ? Object.entries(metadata.maps)
    : []

  return entries.map(([key, rawValue]) => {
    const value = rawValue as any
    const transform = transformFromMetadata(value)
    const floors: SupportedMapFloor[] = Array.isArray(value.floors)
      ? value.floors.map((floor: any) => ({
          name: String(floor.name || ''),
          min_z: Number(floor.min_z),
          max_z: Number(floor.max_z),
          transform: floor.transform ? transformFromMetadata({ transform: floor.transform }) : transform,
          imageFile: safeImageFile(floor.imageFile)
        }))
      : []

    if (floors.some((floor) => !floor.name || !Number.isFinite(floor.min_z) || !Number.isFinite(floor.max_z))) {
      throw new Error(`地图 ${key} 的楼层高度范围无效`)
    }

    return {
      id: `de_${key}`,
      name: mapNames[key] || key,
      transform,
      imageFile: safeImageFile(value.radarImage),
      floors
    }
  })
}

export const radarImageFile = (map: SupportedMap, radarName: string): string | null => {
  if (radarName === 'radar') return map.imageFile || `${map.id}.png`
  if (radarName !== 'radar_lower') return null

  const lowerFloor = map.floors.find((floor) => floor.name === 'lower')
  return lowerFloor?.imageFile || `${map.id}_lower.png`
}

export const mapsResponse = (supportedMaps: SupportedMap[]) => supportedMaps.map((map) => ({
  _id: map.id,
  name: map.name,
  lhmId: map.id,
  game: 'cs2',
  inVetoPool: true,
  isActive: true,
  radars: map.floors.length
    ? map.floors.map((floor, index) => ({
        id: index + 1,
        lhmId: floor.name || `floor${index + 1}`,
        ...floor.transform,
        radar: floor.name === 'lower' ? 'radar_lower' : 'radar',
        visibleOverHeight: floor.max_z,
        visibleUnderHeight: floor.min_z
      }))
    : [{
        id: 1,
        lhmId: 'default',
        ...map.transform,
        radar: 'radar',
        visibleOverHeight: null,
        visibleUnderHeight: null
      }]
}))

export const fallbackMaps: SupportedMap[] = [
  { id: 'de_ancient', name: 'Ancient', transform: legacyTransform(4.26, 2590, 2520), floors: [] },
  { id: 'de_anubis', name: 'Anubis', transform: legacyTransform(5.25, 2830, 2030), floors: [] },
  { id: 'de_dust2', name: 'Dust II', transform: legacyTransform(4.4, 2470, 1255), floors: [] },
  { id: 'de_inferno', name: 'Inferno', transform: legacyTransform(4.91, 2090, 1150), floors: [] },
  { id: 'de_mirage', name: 'Mirage', transform: legacyTransform(5.02, 3240, 3410), floors: [] },
  {
    id: 'de_nuke', name: 'Nuke', imageFile: 'de_nuke_combined.png',
    transform: { originX: 473.1284773048749, originY: 190, pxPerUX: 0.17970119908658634, pxPerUY: -0.18420838669024532 },
    floors: [
      { name: 'upper', min_z: -495, max_z: 14000, transform: { originX: 473.1284773048749, originY: 190, pxPerUX: 0.17970119908658634, pxPerUY: -0.18420838669024532 } },
      { name: 'lower', min_z: -2500, max_z: -495, transform: { originX: 100, originY: 570, pxPerUX: 0.179508593298534, pxPerUY: -0.18166758135658676 } }
    ]
  },
  { id: 'de_cache', name: 'Cache', transform: legacyTransform(5.54, 2020, 2390), floors: [] },
  {
    id: 'de_overpass', name: 'Overpass',
    transform: { originX: 927.3988878244819, originY: 343.8221009185496, pxPerUX: 0.1923720959212443, pxPerUY: -0.19427507725530338 },
    floors: []
  },
  {
    id: 'de_train', name: 'Train',
    transform: { originX: 557.7279495268139, originY: 507.83243734804853, pxPerUX: 0.22712933753943218, pxPerUY: -0.23013108811174968 },
    floors: []
  },
  {
    id: 'de_vertigo', name: 'Vertigo',
    transform: { originX: 784.4793452283254, originY: 255.42597837029027, pxPerUX: 0.19856123172015677, pxPerUY: -0.19820052722907044 },
    floors: [
      { name: 'upper', min_z: 11700, max_z: 14000, transform: { originX: 784.4793452283254, originY: 255.42597837029027, pxPerUX: 0.19856123172015677, pxPerUY: -0.19820052722907044 } },
      { name: 'lower', min_z: 0, max_z: 11700, transform: { originX: 780.5145858437052, originY: 695.4259783702903, pxPerUX: 0.1989615567841087, pxPerUY: -0.19820052722907044 } }
    ]
  }
]
