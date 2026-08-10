const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')
const ts = require('typescript')

const sourcePath = path.resolve(__dirname, '../src/main/server/integrations/live-stats.ts')
const source = fs.readFileSync(sourcePath, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022
  },
  fileName: sourcePath
}).outputText
const compiled = new Module(sourcePath, module)
compiled.filename = sourcePath
compiled.paths = Module._nodeModulePaths(path.dirname(sourcePath))
compiled._compile(output, sourcePath)

const { LiveStatsTracker, buildMapPlayerStats } = compiled.exports

const player = (steamid, side) => ({
  steamid,
  name: steamid,
  avatar: '',
  defaultName: steamid,
  team: { id: side === 'T' ? 'left' : 'right', side },
  stats: { kills: 0, deaths: 0, assists: 0, mvps: 0 },
  state: {
    health: 100,
    round_kills: 0,
    round_killhs: 0,
    round_totaldmg: 0,
    adr: 0
  }
})

const game = (round, players) => ({ map: { name: 'de_nuke', round }, players })
const copy = (value) => JSON.parse(JSON.stringify(value))

const tracker = new LiveStatsTracker()
const start = game(0, [player('A', 'T'), player('B', 'CT'), player('C', 'CT')])
const firstKill = copy(start)
firstKill.players[0].stats.kills = 1
firstKill.players[0].state.round_kills = 1
firstKill.players[0].state.round_totaldmg = 100
firstKill.players[1].stats.deaths = 1
firstKill.players[1].state.health = 0
tracker.recordSnapshot(start, firstKill)

const trade = copy(firstKill)
trade.players[2].stats.kills = 1
trade.players[2].state.round_kills = 1
trade.players[2].state.round_totaldmg = 100
trade.players[0].stats.deaths = 1
trade.players[0].state.health = 0
tracker.recordSnapshot(firstKill, trade)

const events = tracker.consume('de_nuke', 1, trade.players, 'CT')
assert.equal(events.counters.A.firstKills, 1)
assert.equal(events.counters.B.firstDeaths, 1)
assert.equal(events.counters.C.tradeKills, 1)
assert.equal(events.counters.B.tradeDeaths, 1)
assert.equal(events.survivors.has('C'), true)

const round = {
  round: 1,
  winner: 'CT',
  win_type: 'elimination',
  players: {
    A: {
      name: 'A',
      teamId: 'left',
      side: 'T',
      kills: 1,
      deaths: 1,
      assists: 0,
      damage: 100,
      firstKills: 1,
      firstDeaths: 0,
      survived: false
    },
    B: {
      name: 'B',
      teamId: 'right',
      side: 'CT',
      kills: 0,
      deaths: 1,
      assists: 0,
      damage: 0,
      firstKills: 0,
      firstDeaths: 1,
      tradeDeaths: 1,
      survived: false
    },
    C: {
      name: 'C',
      teamId: 'right',
      side: 'CT',
      kills: 1,
      deaths: 0,
      assists: 0,
      damage: 100,
      tradeKills: 1,
      survived: true
    }
  }
}
const stats = buildMapPlayerStats({
  players: trade.players,
  rounds: [round],
  isReversed: false,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 1
})
assert.equal(stats.A.firstKills, 1)
assert.equal(stats.C.tradeKills, 1)
assert.equal(stats.C.roundsPlayed, 1)
assert.equal(stats.C.kast, 100)
assert.ok(stats.C.rating > 0)

console.log('live stats simulation: OK')
