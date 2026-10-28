const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const os = require('node:os')
const path = require('node:path')
const ts = require('typescript')

const managerDir = path.resolve(__dirname, '..')
const candidateRoot = path.resolve(managerDir, '..')
const candidateParent = path.resolve(candidateRoot, '..')
const projectDir = fs.existsSync(path.join(candidateParent, 'docs', 'CODEX_PROJECT_MEMORY.md'))
  ? candidateParent
  : candidateRoot
const radarDir = path.join(managerDir, 'resources', 'map-radars')

const compileTypeScript = (sourcePath, stubs = {}) => {
  const source = fs.readFileSync(sourcePath, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true
    },
    fileName: sourcePath
  }).outputText
  const compiled = new Module(sourcePath, module)
  compiled.filename = sourcePath
  compiled.paths = Module._nodeModulePaths(path.dirname(sourcePath))
  const originalLoad = Module._load
  Module._load = function (request, parent, isMain) {
    if (parent?.filename === sourcePath && Object.hasOwn(stubs, request)) return stubs[request]
    return originalLoad.call(this, request, parent, isMain)
  }
  try {
    compiled._compile(output, sourcePath)
  } finally {
    Module._load = originalLoad
  }
  return compiled.exports
}

const makeRouter = () => {
  const routes = new Map()
  const add = (method) => (routePath, ...handlers) => {
    routes.set(`${method} ${routePath}`, handlers.at(-1))
    return router
  }
  const router = {
    routes,
    get: add('GET'),
    post: add('POST'),
    put: add('PUT'),
    delete: add('DELETE')
  }
  return router
}

const expressStub = { Router: makeRouter }

const makeResponse = () => ({
  statusCode: 200,
  status(code) { this.statusCode = code; return this },
  json(payload) { this.payload = payload; return this },
  sendFile(file) { this.file = file; return this }
})

const imageSize = (filePath) => {
  const bytes = fs.readFileSync(filePath)
  assert.deepEqual(bytes.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
  return { bytes, width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) }
}

const testMapRoutesAndAssets = () => {
  const configPath = path.join(managerDir, 'src', 'main', 'server', 'domains', 'game-maps', 'game-maps.config.ts')
  const mapsConfig = compileTypeScript(configPath)
  const routesPath = path.join(managerDir, 'src', 'main', 'server', 'domains', 'game-maps', 'game-maps.routes.ts')
  const mapRoutes = compileTypeScript(routesPath, {
    express: expressStub,
    electron: { app: { getAppPath: () => managerDir } },
    './game-maps.config': mapsConfig
  })
  const router = mapRoutes.default()
  const mapsResponse = makeResponse()
  router.routes.get('GET /cs2')({}, mapsResponse)
  const maps = mapsResponse.payload
  assert.ok(Array.isArray(maps) && maps.length >= 10, '地图列表路由应返回当前支持地图')

  const nuke = maps.find((map) => map.lhmId === 'de_nuke')
  assert.equal(nuke.radars.length, 2, 'Nuke 应返回上下层两套点位变换')
  assert.equal(nuke.radars[0].radar, 'radar')
  assert.equal(nuke.radars[1].radar, 'radar_lower')
  assert.deepEqual(
    [nuke.radars[0].originX, nuke.radars[0].originY, nuke.radars[0].pxPerUX, nuke.radars[0].pxPerUY],
    [473.1284773048749, 190, 0.17970119908658634, -0.18420838669024532]
  )
  assert.deepEqual(
    [nuke.radars[1].originX, nuke.radars[1].originY, nuke.radars[1].pxPerUX, nuke.radars[1].pxPerUY],
    [100, 570, 0.179508593298534, -0.18166758135658676]
  )

  const expectedSingleFloorTransforms = {
    de_overpass: [927.3988878244819, 343.8221009185496, 0.1923720959212443, -0.19427507725530338],
    de_train: [557.7279495268139, 507.83243734804853, 0.22712933753943218, -0.23013108811174968]
  }
  for (const [mapId, expected] of Object.entries(expectedSingleFloorTransforms)) {
    const map = maps.find((entry) => entry.lhmId === mapId)
    assert.equal(map.radars.length, 1, `${mapId} 应只有一套点位变换`)
    assert.deepEqual(
      [map.radars[0].originX, map.radars[0].originY, map.radars[0].pxPerUX, map.radars[0].pxPerUY],
      expected
    )
  }
  const vertigo = maps.find((map) => map.lhmId === 'de_vertigo')
  assert.deepEqual(
    vertigo.radars.map((radar) => [radar.originX, radar.originY, radar.pxPerUX, radar.pxPerUY]),
    [
      [784.4793452283254, 255.42597837029027, 0.19856123172015677, -0.19820052722907044],
      [780.5145858437052, 695.4259783702903, 0.1989615567841087, -0.19820052722907044]
    ]
  )

  const getImage = router.routes.get('GET /cs2/image/:mapId/:radarName')
  const servedFiles = new Map()
  const requestImage = (mapId, radarName) => {
    const response = makeResponse()
    getImage({ params: { mapId, radarName } }, response)
    assert.equal(response.statusCode, 200, `${mapId}/${radarName} 应有图片`)
    assert.ok(fs.existsSync(response.file), `${mapId}/${radarName} 返回的图片应存在`)
    servedFiles.set(`${mapId}/${radarName}`, response.file)
    return response.file
  }

  requestImage('de_nuke', 'radar')
  requestImage('de_nuke', 'radar_lower')
  const copiedImages = [
    ['de_nuke_combined.png', 'radar-e7a6de7b.png'],
    ['de_overpass.png', 'radar-5ec70095.png'],
    ['de_train.png', 'radar-63202ed1.png'],
    ['de_vertigo.png', 'radar-f15cebdb.png']
  ]
  for (const [targetName, sourceName] of copiedImages) {
    const targetPath = path.join(radarDir, targetName)
    const sourcePath = path.join(managerDir, 'resources', 'default-hud', 'assets', sourceName)
    const target = imageSize(targetPath)
    const source = imageSize(sourcePath)
    assert.deepEqual(target.bytes, source.bytes, `${targetName} 必须逐字节沿用现有原图`)
    assert.equal(target.width, 1024, `${targetName} 应与旧坐标匹配图同为 1024 像素宽`)
    assert.equal(target.height, 1024, `${targetName} 应与旧坐标匹配图同为 1024 像素高`)
  }

  for (const mapId of ['de_overpass', 'de_train', 'de_vertigo']) requestImage(mapId, 'radar')
  assert.equal(path.basename(servedFiles.get('de_nuke/radar')), 'de_nuke_combined.png')
  assert.equal(path.basename(servedFiles.get('de_nuke/radar_lower')), 'de_nuke_lower.png')
  const lexoRadar = fs.readFileSync(path.resolve(managerDir, '..', 'broadcast_hud', 'src', 'HUD', 'Radar', 'LexoRadar', 'LexoRadar.tsx'), 'utf8')
  assert.match(lexoRadar, /maps\[mapName\]\.file/, '单张组合图必须仍由 map.file 作为背景')
  assert.doesNotMatch(lexoRadar, /\bconfig\.file\b/, '不能按 configs[].file 叠加第二张背景')

  const missingMap = makeResponse()
  getImage({ params: { mapId: 'de_missing', radarName: 'radar' } }, missingMap)
  assert.equal(missingMap.statusCode, 404)
}

const makeIo = () => {
  const listeners = new Map()
  const socketEvents = []
  const hudClients = []
  const ioEvents = []
  return {
    listeners,
    socketEvents,
    hudClients,
    ioEvents,
    on(event, callback) { listeners.set(event, callback) },
    emit(event, payload) { ioEvents.push({ event, payload }) },
    to(room) {
      return { emit: (event, payload) => ioEvents.push({ room, event, payload }) }
    },
    in() {
      return { fetchSockets: async () => hudClients }
    }
  }
}

const loadHudRoutes = () => {
  const multer = Object.assign(
    () => ({ single: () => (_req, _res, next) => next?.() }),
    { memoryStorage: () => ({}), diskStorage: () => ({}) }
  )
  const hudPath = path.join(managerDir, 'src', 'main', 'server', 'domains', 'huds', 'hud.routes.ts')
  const hudRoutes = compileTypeScript(hudPath, {
    express: expressStub,
    multer,
    'adm-zip': class AdmZip {},
    '../../database/sqlite': { dbRun: async () => undefined, dbGet: async () => null },
    '../players/player.repository': { PlayerRepository: class {} },
    '../teams/team.repository': { TeamRepository: class {} },
    '../matches/match.repository': { MatchRepository: class {} },
    '../../../paths': { getHudsDir: () => managerDir, getBuiltinHudDir: () => path.join(managerDir, 'resources', 'default-hud') },
    './signature.verifier': { SignatureVerifier: class {} }
  })
  return hudRoutes
}

const testHiddenCommandAndReconnect = async () => {
  const hudRoutes = loadHudRoutes()
  const io = makeIo()
  const router = hudRoutes.default(io)
  const post = router.routes.get('POST /:hudId/director-command')
  const noClientResponse = makeResponse()
  await post({ params: { hudId: 'default' }, body: { command: 'hide_all' } }, noClientResponse)
  assert.deepEqual(noClientResponse.payload, {
    ok: true,
    scene: 'hide_all',
    delivery: 'pending',
    hudClients: 0
  })
  assert.equal(hudRoutes.getDirectorVisibility('default'), false, '无连接时仍须保存隐藏目标')
  assert.equal(io.ioEvents.length, 0, '无 HUD 连接时不能谎称指令已发送')

  let currentFrame = null
  let receivedAt = null
  const socketPath = path.join(managerDir, 'src', 'main', 'server', 'socket.ts')
  const socketModule = compileTypeScript(socketPath, {
    './domains/huds/hud.routes': {
      getDirectorScene: hudRoutes.getDirectorScene,
      getDirectorVisibility: hudRoutes.getDirectorVisibility,
      getHudConfig: async () => ({})
    },
    './server': { getActiveHudId: () => null },
    './integrations/gsi': {
      getLastGSIState: () => currentFrame,
      getLastGSIStateReceivedAt: () => receivedAt
    }
  })
  let timerCallback = null
  const originalSetInterval = global.setInterval
  global.setInterval = (callback) => { timerCallback = callback; return 1 }
  try {
    socketModule.setupSockets(io)
  } finally {
    global.setInterval = originalSetInterval
  }
  assert.equal(typeof timerCallback, 'function', '服务端应检查实时数据是否过期')

  const makeSocket = () => {
    const listeners = new Map()
    const emitted = []
    return {
      listeners,
      emitted,
      on(event, callback) { listeners.set(event, callback) },
      emit(event, payload) { emitted.push({ event, payload }) },
      join(room) { this.joinedRoom = room }
    }
  }
  const serverConnection = io.listeners.get('connection')
  const staleSocket = makeSocket()
  serverConnection(staleSocket)
  await staleSocket.listeners.get('register')('default', false, 'cs2', 'DEFAULT')
  assert.ok(
    staleSocket.emitted.some((item) => item.event === 'hud_action' && item.payload.action === 'directorVisibility' && item.payload.data === 'hide'),
    '重连的 HUD 应收到先前保存的手动隐藏目标'
  )
  assert.ok(
    staleSocket.emitted.some((item) => item.event === 'hud_action' && item.payload.action === 'gsiFreshness' && item.payload.data === 'stale'),
    '重连时没有有效新帧应保持透明'
  )
  assert.equal(staleSocket.emitted.some((item) => item.event === 'update'), false, '不能重放过期旧帧')

  io.hudClients.push(staleSocket)
  const connectedResponse = makeResponse()
  await post({ params: { hudId: 'default' }, body: { command: 'hide_all' } }, connectedResponse)
  assert.deepEqual(connectedResponse.payload, {
    ok: true,
    scene: 'hide_all',
    delivery: 'sent',
    hudClients: 1
  })
  assert.ok(io.ioEvents.some((item) => item.event === 'hud_action' && item.payload.action === 'directorVisibility' && item.payload.data === 'hide'))

  currentFrame = { map: { name: 'de_nuke' } }
  receivedAt = Date.now()
  const freshSocket = makeSocket()
  serverConnection(freshSocket)
  await freshSocket.listeners.get('register')('default', false, 'cs2', 'DEFAULT')
  assert.ok(freshSocket.emitted.some((item) => item.event === 'hud_action' && item.payload.action === 'gsiFreshness' && item.payload.data === 'fresh'))
  assert.ok(freshSocket.emitted.some((item) => item.event === 'update' && item.payload === currentFrame))

  let now = 10_000
  let sampleReceivedAt = null
  const freshnessChanges = []
  const publish = socketModule.createGsiFreshnessPublisher(
    () => sampleReceivedAt,
    (fresh) => freshnessChanges.push(fresh),
    () => now
  )
  publish()
  sampleReceivedAt = now
  publish()
  now += 5000
  publish()
  now += 1
  publish()
  assert.deepEqual(freshnessChanges, [false, true, false], '5 秒边界应显示新帧、到期时转为透明')
}

const testHudSyncScript = async () => {
  const scriptPath = path.join(managerDir, 'scripts', 'build-default-hud.mjs')
  const { syncBuiltHud } = await import(require('node:url').pathToFileURL(scriptPath).href)
  const testOutputDir = path.join(projectDir, 'output', 'director-fix-tests')
  fs.mkdirSync(testOutputDir, { recursive: true })
  const testRoot = fs.mkdtempSync(path.join(testOutputDir, 'build-sync-'))
  const sourceDir = path.join(testRoot, 'built')
  const targetDir = path.join(testRoot, 'default-hud')
  try {
    fs.mkdirSync(path.join(sourceDir, 'assets'), { recursive: true })
    fs.mkdirSync(path.join(targetDir, 'assets'), { recursive: true })
    fs.writeFileSync(path.join(sourceDir, 'index.html'), '<script type="module" src="./assets/index-next.js"></script><link rel="stylesheet" href="./assets/index-next.css">')
    fs.writeFileSync(path.join(sourceDir, 'assets', 'index-next.js'), 'new-js')
    fs.writeFileSync(path.join(sourceDir, 'assets', 'index-next.css'), 'new-css')
    fs.writeFileSync(path.join(sourceDir, 'panel.json'), 'do-not-copy')
    fs.writeFileSync(path.join(targetDir, 'panel.json'), 'keep-current-config')
    fs.writeFileSync(path.join(targetDir, 'assets', 'old.js'), 'keep-old-asset')

    const copied = syncBuiltHud({ sourceDir, targetDir })
    assert.ok(copied.includes('index.html'))
    assert.equal(fs.readFileSync(path.join(targetDir, 'index.html'), 'utf8'), fs.readFileSync(path.join(sourceDir, 'index.html'), 'utf8'))
    assert.equal(fs.readFileSync(path.join(targetDir, 'panel.json'), 'utf8'), 'keep-current-config')
    assert.equal(fs.readFileSync(path.join(targetDir, 'assets', 'old.js'), 'utf8'), 'keep-old-asset')
    assert.equal(fs.readFileSync(path.join(targetDir, 'assets', 'index-next.js'), 'utf8'), 'new-js')
  } finally {
    fs.rmSync(testRoot, { recursive: true, force: true })
  }
}

const testImmediateHudDisconnect = () => {
  const socketPath = path.resolve(managerDir, '..', 'broadcast_hud', 'src', 'API', 'socket.ts')
  const socketEvents = new Map()
  const clientEvents = []
  const client = {
    on(event, callback) { socketEvents.set(event, callback) },
    emit(event, ...args) { clientEvents.push({ event, args }) }
  }
  const actionEvents = []
  const oldWindow = global.window
  const oldSetTimeout = global.setTimeout
  const oldClearTimeout = global.clearTimeout
  let watchdog
  global.setTimeout = (callback, delay) => {
    assert.equal(delay, 5000)
    watchdog = callback
    return 1
  }
  global.clearTimeout = () => { watchdog = null }
  global.window = { parent: {}, location: { href: 'http://localhost/huds/default/index.html' } }
  try {
    compileTypeScript(socketPath, {
      'socket.io-client': { io: () => client },
      '.': { isDev: false, port: 1349 },
      './HUD': {
        GSI: { teams: { left: null, right: null }, damage: null, digest: () => null, digestMIRV: () => undefined },
        hudIdentity: {}
      },
      './contexts/actions': {
        actions: { execute: (...args) => actionEvents.push(args) },
        configs: { save: () => undefined }
      }
    })
    socketEvents.get('update')({ map: { name: 'de_nuke' } })
    assert.deepEqual(actionEvents.at(-1), ['gsiFreshness', 'fresh'])
    assert.equal(typeof watchdog, 'function', '收到有效数据后必须启动独立客户端看门计时')
    watchdog()
    assert.deepEqual(actionEvents.at(-1), ['gsiFreshness', 'stale'], '后台没发断流通知时，客户端也应自行隐藏')
    socketEvents.get('disconnect')('transport close')
    assert.deepEqual(actionEvents.at(-1), ['gsiFreshness', 'disconnected'], 'Socket 断开时客户端必须立刻隐藏全部画面')
    assert.equal(clientEvents.length, 0, '断开时不应试图通过已断开的 Socket 发隐藏指令')
  } finally {
    global.setTimeout = oldSetTimeout
    global.clearTimeout = oldClearTimeout
    if (oldWindow === undefined) delete global.window
    else global.window = oldWindow
  }

  const layoutPath = path.resolve(managerDir, '..', 'broadcast_hud', 'src', 'HUD', 'Layout', 'Layout.tsx')
  const layout = fs.readFileSync(layoutPath, 'utf8')
  assert.match(layout, /const showGameHud = activeScene === "game" && gsiFresh/)
  assert.match(layout, /if \(!directorVisible \|\| !hudConnected\) return null/)
  const staleHandler = layout.match(/useAction\('gsiFreshness',[\s\S]*?\n  \}, \[\], true\)/)?.[0] || ''
  assert.doesNotMatch(staleHandler, /setDirectorVisible/, 'GSI 断流不能清除手动隐藏状态')
}

const main = async () => {
  testMapRoutesAndAssets()
  await testHiddenCommandAndReconnect()
  await testHudSyncScript()
  testImmediateHudDisconnect()
  console.log('HUD 小地图、断流隐藏、重连隐藏目标、实际图片路由和内置 HUD 同步检查通过。')
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
