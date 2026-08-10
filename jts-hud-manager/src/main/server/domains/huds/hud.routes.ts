import { Router, Request, Response } from 'express'
import fs from 'fs'
import path from 'path'
import { Server } from 'socket.io'
import multer from 'multer'
import AdmZip from 'adm-zip'
import { dbRun, dbGet } from '../../database/sqlite'
import { PlayerRepository } from '../players/player.repository'
import { TeamRepository } from '../teams/team.repository'
import { MatchRepository } from '../matches/match.repository'
import { getHudsDir, getBuiltinHudDir } from '../../../paths'
import { SignatureVerifier } from './signature.verifier'

// --- Lots of AI generated functions in here, be careful ---

// Files store at userData/huds/:hudId/uploads/
const hudUploadStorage = multer.diskStorage({
  destination: (req, _file, cb) => {
    const dir = path.join(getHudsDir(), req.params.hudId as string, 'uploads')
    fs.mkdirSync(dir, { recursive: true })
    cb(null, dir)
  },
  filename: (_req, file, cb) => {
    const unique = Date.now() + '-' + Math.round(Math.random() * 1e9)
    cb(null, unique + path.extname(file.originalname))
  }
})
const hudUpload = multer({ storage: hudUploadStorage })

// processed with adm-zip before writing to disk
const zipUpload = multer({ storage: multer.memoryStorage() })

const playerRepo = new PlayerRepository()
const teamRepo = new TeamRepository()
const matchRepo = new MatchRepository()
const BUILTIN_HUD_CACHE_VERSION = '80gotv-cn-obs-10'
const directorScenes = new Map<string, string>()
const directorVisibility = new Map<string, boolean>()

export const getDirectorScene = (hudId: string): string => directorScenes.get(hudId) || 'auto'
export const getDirectorVisibility = (hudId: string): boolean => directorVisibility.get(hudId) !== false

const emitDirectorAction = (io: Server, hudId: string, action: string, data: string): void => {
  if (action === 'directorScene') directorScenes.set(hudId, data || 'game')
  if (action === 'directorVisibility') directorVisibility.set(hudId, data !== 'hide')
  io.emit('hud_action', { action, data: data ?? null })
}

const applyDirectorCommand = async (io: Server, hudId: string, command: string): Promise<string> => {
  const normalized = String(command || '').trim().toLowerCase()
  if (normalized === 'hide_all' || normalized === 'hide') {
    emitDirectorAction(io, hudId, 'bpShowcaseState', 'hide')
    emitDirectorAction(io, hudId, 'directorVisibility', 'hide')
    return 'hide_all'
  }
  if (normalized === 'bp' || normalized === 'bp_show') {
    emitDirectorAction(io, hudId, 'directorVisibility', 'show')
    emitDirectorAction(io, hudId, 'directorScene', 'game')
    emitDirectorAction(io, hudId, 'bpShowcaseState', 'hide')
    await new Promise((resolve) => setTimeout(resolve, 80))
    emitDirectorAction(io, hudId, 'bpShowcaseState', 'show')
    return 'bp'
  }
  const scenes: Record<string, string> = {
    auto: 'auto',
    game: 'game',
    pause_tactical: 'pause_current',
    pause_current: 'pause_current',
    pause_technical: 'pause_technical',
    halftime: 'halftime',
    map_end: 'map_end',
    series_end: 'series_end'
  }
  const scene = scenes[normalized]
  if (!scene) throw new Error(`未知导播命令: ${command}`)
  emitDirectorAction(io, hudId, 'directorVisibility', 'show')
  emitDirectorAction(io, hudId, 'bpShowcaseState', 'hide')
  emitDirectorAction(io, hudId, 'directorScene', 'game')
  if (scene !== 'game') await new Promise((resolve) => setTimeout(resolve, 80))
  emitDirectorAction(io, hudId, 'directorScene', scene)
  return scene
}

// Enrich raw config (which stores plain IDs) with full player/team/match objects,
// matching the shape the HUD's InputMapper/useOnConfigChange expects.
const enrichHudConfig = async (
  hudId: string,
  rawConfig: Record<string, any>
): Promise<Record<string, any>> => {
  const hudDir = hudId === 'default' ? getBuiltinHudDir() : path.join(getHudsDir(), hudId)
  const panelPath = path.join(hudDir, 'panel.json')
  if (!fs.existsSync(panelPath)) return rawConfig

  let panel: { name: string; inputs: { type: string; name: string }[] }[]
  try {
    panel = JSON.parse(fs.readFileSync(panelPath, 'utf-8'))
  } catch {
    return rawConfig
  }

  const enriched: Record<string, any> = { ...rawConfig }

  for (const section of panel) {
    const sectionData = enriched[section.name]
    if (!sectionData || typeof sectionData !== 'object') continue
    const enrichedSection: Record<string, any> = { ...sectionData }

    for (const input of section.inputs) {
      const rawValue = enrichedSection[input.name]
      if (!rawValue || typeof rawValue !== 'string') continue

      if (input.type === 'player') {
        const player = await playerRepo.getPlayerById(rawValue)
        enrichedSection[input.name] = { type: 'player', id: rawValue, player: player ?? null }
      } else if (input.type === 'team') {
        const team = await teamRepo.getTeamById(rawValue)
        enrichedSection[input.name] = { type: 'team', id: rawValue, team: team ?? null }
      } else if (input.type === 'match') {
        const match = await matchRepo.getMatchById(rawValue)
        enrichedSection[input.name] = { type: 'match', id: rawValue, match: match ?? null }
      }
    }
    enriched[section.name] = enrichedSection
  }

  return enriched
}

// Raw config from DB (plain IDs) — used by the panel UI so selects can match option values
const getRawHudConfig = async (hudId: string): Promise<Record<string, any>> => {
  const row = await dbGet('SELECT config_data FROM hud_configs WHERE hud_id = ?', [hudId])
  try {
    return row ? JSON.parse(row.config_data) : {}
  } catch {
    return {}
  }
}

// Enriched config (IDs resolved to full objects) — used by socket emissions to the HUD
export const getHudConfig = async (hudId: string): Promise<Record<string, any>> => {
  const raw = await getRawHudConfig(hudId)
  return enrichHudConfig(hudId, raw)
}

const findThumbFile = (hudDir: string): string | null => {
  const thumbPng = path.join(hudDir, 'thumb.png')
  const thumbJpg = path.join(hudDir, 'thumb.jpg')
  if (fs.existsSync(thumbPng)) return 'thumb.png'
  if (fs.existsSync(thumbJpg)) return 'thumb.jpg'
  return null
}

const createHudRouter = (io: Server) => {
  const router = Router()

  // POST /api/huds/upload-zip. Zip must contain a hud.json (and optional 'key' file for signed HUDs)
  router.post('/upload-zip', zipUpload.single('hud'), async (req: Request, res: Response) => {
    if (!req.file) return res.status(400).json({ error: 'No zip file provided' })
    try {
      const zip = new AdmZip(req.file.buffer)
      const entries = zip.getEntries()

      // Find hud.json at root or one level deep
      const hudJsonEntry = entries.find(
        (e) =>
          !e.isDirectory && (e.entryName === 'hud.json' || /^[^/]+\/hud\.json$/.test(e.entryName))
      )
      if (!hudJsonEntry)
        return res.status(400).json({
          error:
            'No hud.json found. Make sure hud.json is at the root or inside the top-level folder.'
        })

      // Determine prefix to strip and hud id
      let prefix = ''
      let hudId: string
      if (hudJsonEntry.entryName === 'hud.json') {
        // hud.json at root, use zip filename as id
        hudId = path
          .basename(req.file.originalname, '.zip')
          .replace(/[^a-zA-Z0-9_-]/g, '-')
          .toLowerCase()
        prefix = ''
      } else {
        // hud.json one level deep, use folder name as id
        prefix = hudJsonEntry.entryName.replace(/\/hud\.json$/, '') + '/'
        hudId = prefix.slice(0, -1)
      }

      const hudDir = path.join(getHudsDir(), hudId)
      fs.mkdirSync(hudDir, { recursive: true })

      // Check if this is a signed HUD (has 'key' file)
      const keyEntry = entries.find(
        (e) => !e.isDirectory && (e.entryName === 'key' || e.entryName === prefix + 'key')
      )
      const isSigned = !!keyEntry

      // Extract all files that belong to this HUD
      for (const entry of entries) {
        if (entry.isDirectory) continue
        if (prefix && !entry.entryName.startsWith(prefix)) continue
        const relativePath = prefix ? entry.entryName.slice(prefix.length) : entry.entryName
        if (!relativePath) continue
        const destPath = path.join(hudDir, relativePath)
        fs.mkdirSync(path.dirname(destPath), { recursive: true })
        fs.writeFileSync(destPath, entry.getData())
      }

      const hudJsonContent = hudJsonEntry.getData().toString('utf-8')
      let hudData: Record<string, any> = {}

      // Parse hud.json - handle both signed and unsigned
      if (isSigned && keyEntry) {
        try {
          const publicKey = keyEntry.getData().toString('utf-8')
          const decoded = SignatureVerifier.verifySignedFile(hudJsonContent, publicKey)
          hudData = JSON.parse(decoded)
        } catch {
          // If verification fails, try to parse as regular JSON
          hudData = JSON.parse(hudJsonContent)
        }
      } else {
        hudData = JSON.parse(hudJsonContent)
      }

      return res.json({
        ok: true,
        id: hudId,
        config: hudData,
        isSigned
      })
    } catch (e: any) {
      return res.status(500).json({ error: e.message })
    }
  })

  // GET /api/huds — list all available HUDs
  router.get('/', (_req: Request, res: Response) => {
    try {
      const hudsDir = getHudsDir()
      const directories = fs
        .readdirSync(hudsDir, { withFileTypes: true })
        .filter((dirent) => dirent.isDirectory())
        .map((dirent) => dirent.name)

      const availableHuds: {
        id: string
        config: any
        url: string
        thumb?: string
        hasPanel: boolean
        canDelete: boolean
        isSigned?: boolean
        signatureVerified?: boolean
      }[] = []

      // Prepend default hud which cannot be deleted
      const builtinDir = getBuiltinHudDir()
      const builtinHudJson = path.join(builtinDir, 'hud.json')
      if (fs.existsSync(builtinHudJson)) {
        try {
          const result = SignatureVerifier.verifyAndParseHudJson(builtinHudJson)
          const config = result.data
          const thumbFilename = findThumbFile(builtinDir)
          const panelPath = path.join(builtinDir, 'panel.json')
          const signatureStatus = SignatureVerifier.getHudSignatureStatus(builtinDir)
          availableHuds.push({
            id: 'default',
            config,
            url: `http://127.0.0.1:${process.env.HUD_PORT || 1349}/huds/default/index.html?isProd=1&v=${BUILTIN_HUD_CACHE_VERSION}`,
            thumb: thumbFilename
              ? `http://localhost:${process.env.HUD_PORT || 1349}/huds/default/${thumbFilename}`
              : undefined,
            hasPanel: fs.existsSync(panelPath),
            canDelete: false,
            isSigned: signatureStatus.isSigned,
            signatureVerified: signatureStatus.isSigned && !result.error
          })
        } catch {
          // Skip if hud.json is invalid
        }
      }

      for (const dirName of directories) {
        const hudJsonPath = path.join(hudsDir, dirName, 'hud.json')
        if (fs.existsSync(hudJsonPath)) {
          const result = SignatureVerifier.verifyAndParseHudJson(hudJsonPath)
          const hudData = result.data
          const thumbFilename = findThumbFile(path.join(hudsDir, dirName))
          const panelPath = path.join(hudsDir, dirName, 'panel.json')
          const signatureStatus = SignatureVerifier.getHudSignatureStatus(
            path.join(hudsDir, dirName)
          )
          availableHuds.push({
            id: dirName,
            config: hudData,
            url: `http://127.0.0.1:${process.env.HUD_PORT || 1349}/huds/${dirName}/index.html?isProd=1`,
            thumb: thumbFilename
              ? `http://localhost:${process.env.HUD_PORT || 1349}/huds/${dirName}/${thumbFilename}`
              : undefined,
            hasPanel: fs.existsSync(panelPath),
            canDelete: true,
            isSigned: signatureStatus.isSigned,
            signatureVerified: signatureStatus.isSigned && !result.error
          })
        }
      }
      res.json(availableHuds)
    } catch (error: any) {
      res.status(500).json({ error: error.message })
    }
  })

  // GET /api/huds/:hudId/panel — return panel.json (handle both signed and unsigned)
  router.get('/:hudId/panel', (req: Request, res: Response) => {
    const hudId = req.params.hudId as string
    const hudDir = hudId === 'default' ? getBuiltinHudDir() : path.join(getHudsDir(), hudId)
    const panelPath = path.join(hudDir, 'panel.json')
    if (!fs.existsSync(panelPath))
      return res.status(404).json({ error: 'No panel.json found for this HUD.' })
    try {
      const fileContent = fs.readFileSync(panelPath, 'utf-8')
      const signatureStatus = SignatureVerifier.getHudSignatureStatus(hudDir)

      // Only try to verify if HUD is signed AND the file content looks like a JWT
      if (signatureStatus.isSigned && signatureStatus.publicKey) {
        const jwtPattern = /^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/
        if (jwtPattern.test(fileContent.trim())) {
          try {
            const decoded = SignatureVerifier.verifySignedFile(
              fileContent,
              signatureStatus.publicKey
            )
            return res.json(JSON.parse(decoded))
          } catch (error) {
            return res.status(403).json({
              error: `Panel signature verification failed: ${error instanceof Error ? error.message : String(error)}`
            })
          }
        }
      }

      // Not signed or not a JWT, parse as regular JSON
      return res.json(JSON.parse(fileContent))
    } catch (e: any) {
      return res.status(500).json({ error: e.message })
    }
  })

  // GET /api/huds/:hudId/config — return persisted config
  router.get('/:hudId/config', async (req: Request, res: Response) => {
    try {
      res.json(await getRawHudConfig(req.params.hudId as string))
    } catch (e: any) {
      res.status(500).json({ error: e.message })
    }
  })

  // PUT /api/huds/:hudId/config — save config and emit to HUD
  router.put('/:hudId/config', async (req: Request, res: Response) => {
    const { hudId } = req.params
    const config = req.body
    try {
      await dbRun(
        'INSERT INTO hud_configs (hud_id, config_data) VALUES (?, ?) ON CONFLICT(hud_id) DO UPDATE SET config_data = excluded.config_data',
        [hudId, JSON.stringify(config)]
      )
      // Emit enriched config (raw IDs → full objects) so the HUD receives the expected shape
      const enriched = await enrichHudConfig(hudId as string, config)
      io.emit('hud_config', enriched)
      res.json({ ok: true })
    } catch (e: any) {
      res.status(500).json({ error: e.message })
    }
  })

  // POST /api/huds/:hudId/action — fire a panel action to the HUD
  router.post('/:hudId/action', (req: Request, res: Response) => {
    const { action, data } = req.body
    if (!action) return res.status(400).json({ error: 'action is required' })
    if (action === 'directorScene') directorScenes.set(req.params.hudId as string, String(data || 'game'))
    if (action === 'directorVisibility') directorVisibility.set(req.params.hudId as string, data !== 'hide')
    io.emit('hud_action', { action, data: data ?? null })
    return res.json({ ok: true })
  })

  // POST /api/huds/:hudId/director-command — one command shared by buttons and shortcuts
  router.post('/:hudId/director-command', async (req: Request, res: Response) => {
    try {
      const scene = await applyDirectorCommand(io, req.params.hudId as string, req.body?.command)
      return res.json({ ok: true, scene })
    } catch (error: any) {
      return res.status(400).json({ ok: false, error: error?.message || '导播命令失败' })
    }
  })

  router.get('/:hudId/director-status', async (req: Request, res: Response) => {
    const clients = await io.in('huds').fetchSockets()
    return res.json({
      ok: true,
      scene: getDirectorScene(req.params.hudId as string),
      visible: getDirectorVisibility(req.params.hudId as string),
      hudClients: clients.length
    })
  })

  // DELETE /api/huds/:hudId — remove the HUD directory and its DB config
  router.delete('/:hudId', async (req: Request, res: Response) => {
    const hudId = path.basename(req.params.hudId as string) // prevent traversal
    if (hudId === 'default')
      return res.status(403).json({ error: 'The built-in HUD cannot be deleted.' })
    const hudDir = path.join(getHudsDir(), hudId)
    try {
      if (fs.existsSync(hudDir)) fs.rmSync(hudDir, { recursive: true, force: true })
      await dbRun('DELETE FROM hud_configs WHERE hud_id = ?', [hudId])
      return res.json({ ok: true })
    } catch (e: any) {
      return res.status(500).json({ error: e.message })
    }
  })

  // GET /api/huds/:hudId/:sectionName/:inputName — return a specific config value (e.g. images array)
  // Used by HUDs to fetch multi-image lists directly (isDev & cache params are accepted but ignored)
  router.get('/:hudId/:sectionName/:inputName', async (req: Request, res: Response) => {
    try {
      const raw = await getRawHudConfig(req.params.hudId as string)
      const value = raw?.[req.params.sectionName as string]?.[req.params.inputName as string]
      // Always return an array for images fields; fall back to empty array
      res.json(Array.isArray(value) ? value : value !== undefined ? [value] : [])
    } catch (e: any) {
      res.status(500).json({ error: e.message })
    }
  })

  // POST /api/huds/:hudId/upload — upload an image, store under huds/:hudId/uploads/
  router.post('/:hudId/upload', hudUpload.single('image'), (req: Request, res: Response) => {
    if (!req.file) {
      return res.status(400).json({ error: 'No file provided' })
    }
    // URL is served by the existing '/huds' static mount in server.ts
    const url = `/huds/${req.params.hudId}/uploads/${req.file.filename}`
    return res.json({ url, filename: req.file.filename })
  })

  // DELETE /api/huds/:hudId/upload/:filename — delete an uploaded image file
  router.delete('/:hudId/upload/:filename', (req: Request, res: Response) => {
    // Prevent path traversal
    const filename = path.basename(req.params.filename as string)
    const filePath = path.join(getHudsDir(), req.params.hudId as string, 'uploads', filename)
    try {
      if (fs.existsSync(filePath)) fs.unlinkSync(filePath)
      res.json({ ok: true })
    } catch (e: any) {
      res.status(500).json({ error: e.message })
    }
  })

  // GET /api/huds/:hudId/verify-file/:filename — verify a file's signature (if HUD is signed)
  // Returns { verified: boolean, error?: string, content?: string }
  router.get('/:hudId/verify-file/:filename', (req: Request, res: Response) => {
    try {
      const hudId = req.params.hudId as string
      const filename = path.basename(req.params.filename as string)
      const hudDir = hudId === 'default' ? getBuiltinHudDir() : path.join(getHudsDir(), hudId)
      const filePath = path.join(hudDir, filename)

      if (!fs.existsSync(filePath)) {
        return res.status(404).json({ error: 'File not found' })
      }

      const signatureStatus = SignatureVerifier.getHudSignatureStatus(hudDir)

      // If HUD is not signed, just return as verified
      if (!signatureStatus.isSigned) {
        return res.json({ verified: false, reason: 'HUD is not signed' })
      }

      // HUD is signed, verify the file
      const fileContent = fs.readFileSync(filePath, 'utf-8')
      const result = SignatureVerifier.tryVerifyFile(fileContent, signatureStatus.publicKey || null)

      return res.json({
        verified: result.verified,
        error: result.error
      })
    } catch (error) {
      return res.status(500).json({
        error: `Verification failed: ${error instanceof Error ? error.message : String(error)}`
      })
    }
  })

  // GET /api/huds/:hudId/signature-status — get the signature status of a HUD
  router.get('/:hudId/signature-status', (req: Request, res: Response) => {
    try {
      const hudId = req.params.hudId as string
      const hudDir = hudId === 'default' ? getBuiltinHudDir() : path.join(getHudsDir(), hudId)

      if (!fs.existsSync(hudDir)) {
        return res.status(404).json({ error: 'HUD not found' })
      }

      const signatureStatus = SignatureVerifier.getHudSignatureStatus(hudDir)
      const hudJsonPath = path.join(hudDir, 'hud.json')
      const parseResult = SignatureVerifier.verifyAndParseHudJson(hudJsonPath)

      return res.json({
        isSigned: signatureStatus.isSigned,
        hasPublicKey: !!signatureStatus.publicKey,
        hud_json_verified: parseResult.isSigned && !parseResult.error,
        error: parseResult.error || null
      })
    } catch (error) {
      return res.status(500).json({
        error: `Failed to get signature status: ${error instanceof Error ? error.message : String(error)}`
      })
    }
  })

  return router
}

export default createHudRouter
