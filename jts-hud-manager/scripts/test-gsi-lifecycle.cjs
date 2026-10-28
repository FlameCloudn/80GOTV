const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')
const ts = require('typescript')

const sourcePath = path.resolve(__dirname, '../src/main/server/integrations/gsi.ts')
const source = fs.readFileSync(sourcePath, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022
  },
  fileName: sourcePath
}).outputText

let currentMatch = null
const stubs = {
  '../domains/matches/match.service': {
    MatchService: class {
      async getCurrentMatch() { return currentMatch }
    }
  },
  '../domains/teams/team.service': {
    TeamService: class { async getTeamById() { return null } }
  },
  '../domains/players/player.repository': {
    PlayerRepository: class { async getPlayers() { return [] } }
  },
  '../domains/settings/settings.routes': { getSettings: async () => ({}) },
  '../database/sqlite': { dbReady: Promise.resolve(), dbGet: async () => null },
  './80gotv': {
    applyWebsitePlayerPresentation: (payload) => payload,
    getWebsitePlayerPresentation: () => null,
    queueWebsiteLiveData: () => undefined,
    queueWebsiteMapResult: async () => undefined
  },
  './live-stats': {
    buildMapPlayerStats: () => ({}),
    liveStatsTracker: {
      resetMap: () => undefined,
      recordSnapshot: () => undefined,
      consume: () => ({ counters: {}, survivors: new Set(), hadKillEvents: false })
    }
  }
}

const compiled = new Module(sourcePath, module)
compiled.filename = sourcePath
compiled.paths = Module._nodeModulePaths(path.dirname(sourcePath))
const originalLoad = Module._load
Module._load = function (request, parent, isMain) {
  if (parent?.filename === sourcePath && Object.prototype.hasOwnProperty.call(stubs, request)) {
    return stubs[request]
  }
  return originalLoad.call(this, request, parent, isMain)
}
try {
  compiled._compile(output, sourcePath)
} finally {
  Module._load = originalLoad
}

const {
  buildDamageObservations,
  buildOfficialBaselines,
  captureCompleteDamageRound,
  captureRoundFrameSnapshot,
  getLastGSIStateReceivedAt,
  isReversedForMap,
  isFreshGsiStateAt,
  mapLifecycleKey,
  mergeWarmupTotals,
  stableTeamId
} = compiled.exports

for (const [name, value] of Object.entries({
  buildDamageObservations,
  buildOfficialBaselines,
  captureCompleteDamageRound,
  captureRoundFrameSnapshot,
  getLastGSIStateReceivedAt,
  isReversedForMap,
  isFreshGsiStateAt,
  mapLifecycleKey,
  mergeWarmupTotals,
  stableTeamId
})) {
  assert.equal(typeof value, 'function', `缺少生命周期检查函数：${name}`)
}

const player = (steamid, kills, deaths = 0) => ({
  steamid,
  name: steamid,
  stats: { kills, deaths, assists: 0, mvps: 0 },
  team: { id: 'left', side: 'CT' },
  state: { round_totaldmg: 0 }
})

// 已经是本场左右队伍的稳定 ID 时，半场标记不能再把它互换。
assert.equal(stableTeamId('left', 'CT', 'left', 'right', true, 'left'), 'left')
assert.equal(stableTeamId('right', 'T', 'left', 'right', true, 'left'), 'right')
// 旧格式只给 CT/T 时，仍可按当前侧一次映射到稳定 ID。
assert.equal(stableTeamId('CT', 'CT', 'left', 'right', true, 'left'), 'right')
assert.equal(stableTeamId('T', 'T', 'left', 'right', true, 'left'), 'left')
assert.equal(isReversedForMap({ openingCtTeamId: 'left', reverseSide: false }, 'right', 'left'), true)
assert.equal(isReversedForMap({ openingCtTeamId: 'left', reverseSide: false }, 'CT', 'T'), false)

const baseIdentity = { matchId: '80gotv-match-12', mapName: 'de_nuke', mapSlot: 1, mapGeneration: 0 }
assert.notEqual(
  mapLifecycleKey(baseIdentity),
  mapLifecycleKey({ ...baseIdentity, matchId: '80gotv-match-13' })
)
assert.notEqual(
  mapLifecycleKey(baseIdentity),
  mapLifecycleKey({ ...baseIdentity, mapSlot: 2 })
)
assert.notEqual(
  mapLifecycleKey(baseIdentity),
  mapLifecycleKey({ ...baseIdentity, mapGeneration: 1 })
)

// 排队写入前复制事件帧，后续 GSI 帧不能改写已经排队的数据。
const score = { map: { name: 'de_nuke', round: 4, team_ct: { id: 'left', score: 3 } } }
const current = { players: [player('A', 2)] }
const eventMatch = {
  id: baseIdentity.matchId,
  left: { id: 'left', wins: 0 },
  right: { id: 'right', wins: 0 },
  matchType: 'bo3',
  vetos: [{ teamId: 'left', mapName: 'de_nuke', mapSlot: 1, mapGeneration: 0, side: 'CT', type: 'pick', mapEnd: false }]
}
const snapshot = captureRoundFrameSnapshot(score, current, baseIdentity, eventMatch)
score.map.team_ct.score = 8
current.players[0].stats.kills = 9
eventMatch.left.id = 'changed-after-queue'
assert.equal(snapshot.score.map.team_ct.score, 3)
assert.equal(snapshot.players[0].stats.kills, 2)
assert.equal(snapshot.identity.mapGeneration, 0)
assert.equal(snapshot.match.left.id, 'left')

// 开局时缺席的选手仍保留最后一次热身基线。
const warmup = mergeWarmupTotals(new Map(), [player('A', 2), player('B', 0)])
const official = buildOfficialBaselines(warmup, [player('B', 0)])
assert.equal(official.get('A').kills, 2)
assert.equal(official.get('B').kills, 0)
const warmupAfterOnePlayerLeaves = mergeWarmupTotals(warmup, [player('B', 0, 1)])
assert.equal(warmupAfterOnePlayerLeaves.get('A').kills, 2)

// 仅统计实际观测到的完整回合，并且同一回合不会被重复加算；终场回合也在事件回调中记录。
const damageTotals = new Map()
captureCompleteDamageRound(damageTotals, 1, [
  { steamid: 'A', state: { round_totaldmg: 40 } },
  { steamid: 'B', state: { round_totaldmg: 15 } }
])
captureCompleteDamageRound(damageTotals, 1, [
  { steamid: 'A', state: { round_totaldmg: 50 } }
])
captureCompleteDamageRound(damageTotals, 1, [
  { steamid: 'A', state: { round_totaldmg: 40 } }
])
captureCompleteDamageRound(damageTotals, 2, [
  { steamid: 'A', state: { round_totaldmg: 70 } }
])
assert.deepEqual(buildDamageObservations(damageTotals).A, { damage: 120, rounds: 2 })
assert.deepEqual(buildDamageObservations(damageTotals).B, { damage: 15, rounds: 1 })

assert.equal(isFreshGsiStateAt(10_000, 15_000), true)
assert.equal(isFreshGsiStateAt(9_999, 15_000), false)
assert.equal(isFreshGsiStateAt(null, 15_000), false)
assert.equal(typeof getLastGSIStateReceivedAt, 'function')

console.log('GSI 生命周期回归检查通过：稳定队伍 ID、帧快照、地图代次、热身基线、完整回合伤害和 5 秒有效帧。')
