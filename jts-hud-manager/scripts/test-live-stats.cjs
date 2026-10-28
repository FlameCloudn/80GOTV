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

const snapshotKills = (ordered) => {
  const tracker = new LiveStatsTracker()
  const before = game(0, ordered.map(([id, side]) => player(id, side)))
  const after = copy(before)
  after.players.forEach((entry) => {
    if (entry.steamid.startsWith('K')) entry.state.round_kills = 1
    if (entry.steamid.startsWith('V')) {
      entry.state.health = 0
      entry.stats.deaths = 1
    }
  })
  tracker.recordSnapshot(before, after)
  return tracker.consume('de_nuke', 1, after.players, 'T').counters
}
const orderedSnapshot = snapshotKills([['KA', 'T'], ['KB', 'T'], ['V1', 'CT'], ['V2', 'CT']])
const shuffledSnapshot = snapshotKills([['V2', 'CT'], ['KB', 'T'], ['V1', 'CT'], ['KA', 'T']])
assert.equal(orderedSnapshot.KA.firstKills, 1)
assert.equal(shuffledSnapshot.KA.firstKills, 1)

const eventTracker = new LiveStatsTracker()
const eventBefore = game(0, [player('A', 'T'), player('B', 'CT'), player('C', 'CT')])
const eventAfter = copy(eventBefore)
eventAfter.players[0].state.round_kills = 1
eventAfter.players[1].state.health = 0
eventAfter.players[1].stats.deaths = 1
eventAfter.players[2].state.health = 0
eventAfter.players[2].stats.deaths = 1
eventTracker.recordSnapshot(eventBefore, eventAfter)
eventTracker.recordKill(game(0, eventAfter.players), {
  killer: eventAfter.players[0], victim: eventAfter.players[2]
})
const eventPriority = eventTracker.consume('de_nuke', 1, eventAfter.players, 'T').counters
assert.equal(eventPriority.A.firstKills, 1)
assert.equal(eventPriority.B.firstDeaths, 0)
assert.equal(eventPriority.C.firstDeaths, 1)

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

// 和网站同一套公式（utils/stats_calc.py）：Impact 最低记 0，Rating 用原值算
assert.equal(stats.A.impact, 1.72)
assert.equal(stats.A.rating, 1.44)
assert.equal(stats.B.impact, 0)
assert.equal(stats.B.rating, 0.26)
assert.equal(stats.C.impact, 1.72)
assert.equal(stats.C.rating, 1.98)
// 分 T / CT 的 Rating 也是同一套公式
assert.equal(stats.C.ctStats.rating, 1.98)

// 回合都记到了：按回合相加，计分板的数字不参与
const complete = buildMapPlayerStats({
  players: trade.players,
  rounds: [round],
  isReversed: false,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 1,
  scoreboard: { C: { kills: 9, deaths: 9, assists: 9 } },
  damageObservations: { C: { damage: 1000, rounds: 1 } }
})
assert.equal(complete.C.kills, 1)
assert.equal(complete.C.deaths, 0)
assert.equal(complete.C.roundsRecorded, 1)
assert.equal(complete.C.damage, 100)

const lateRow = (kills, deaths, assists, damage, survived) => ({
  name: 'C', teamId: 'right', side: 'CT', kills, deaths, assists, damage, survived
})

// 终场计分板 KDA 优先；快照累计伤害比仅保存到的两回合更完整，ADR 按观察样本均值估算。
const estimated = buildMapPlayerStats({
  players: trade.players,
  rounds: [null, null, { round: 19, winner: 'CT', players: { C: lateRow(1, 1, 0, 400, false) } },
    { round: 20, winner: 'T', players: { C: lateRow(0, 0, 0, 200, false) } }],
  isReversed: true,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 20,
  scoreboard: { C: { kills: 10, deaths: 8, assists: 2 } },
  damageObservations: { C: { damage: 1600, rounds: 20 } }
})
assert.deepEqual(
  [estimated.C.kills, estimated.C.deaths, estimated.C.assists, estimated.C.roundsPlayed,
    estimated.C.damage, estimated.C.adr, estimated.C.kastRounds],
  [10, 8, 2, 20, 1600, 80, 12]
)
assert.equal(estimated.C.rating, 0.98)
assert.equal(estimated.C.teamId, 'right')

// 当前玩家的 GSI 队伍 ID 已稳定对应比赛队伍；换边后也不能把这个 ID 再交换一次。
const stableTeam = buildMapPlayerStats({
  players: [player('S', 'CT')],
  rounds: [],
  isReversed: true,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 10
})
assert.equal(stableTeam.S.teamId, 'right')

// 中途才连上（4 回合只记到后 2 回合）：KDA 使用终场计分板，伤害按完整回合观测样本均值估算
const late = buildMapPlayerStats({
  players: trade.players,
  rounds: [null, null, { round: 3, winner: 'CT', players: { C: lateRow(2, 0, 0, 180, true) } },
    { round: 4, winner: 'T', players: { C: lateRow(1, 1, 1, 120, false) } }],
  isReversed: false,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 4,
  scoreboard: { C: { kills: 6, deaths: 2, assists: 1 } },
  damageObservations: { C: { damage: 300, rounds: 2 } }
})
assert.deepEqual(
  [late.C.kills, late.C.deaths, late.C.assists, late.C.damage, late.C.kastRounds],
  [6, 2, 1, 600, 4]
)
assert.equal(late.C.roundsPlayed, 4)
assert.equal(late.C.roundsRecorded, 2)
assert.equal(late.C.adr, 150)
assert.equal(late.C.impact, 2.89)
assert.equal(late.C.rating, 2.33)

// 观测伤害样本缺失时，只能用 GSI 的 ADR 估算整图伤害，不能把部分回合乘比例
const partialWithoutDamageObservations = copy(trade.players)
partialWithoutDamageObservations[2].state.adr = 55
const partialBlind = buildMapPlayerStats({
  players: partialWithoutDamageObservations,
  rounds: [null, null, { round: 3, winner: 'CT', players: { C: lateRow(2, 0, 0, 180, true) } },
    { round: 4, winner: 'T', players: { C: lateRow(1, 1, 1, 120, false) } }],
  isReversed: false,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 4,
  scoreboard: { C: { kills: 6, deaths: 2, assists: 1 } }
})
assert.equal(partialBlind.C.damage, 220)
assert.equal(partialBlind.C.adr, 55)

// 不完整回合的 KAST 直接采用终场 KDA 可确认的最低回合数
const partialKast = buildMapPlayerStats({
  players: [player('E', 'T')],
  rounds: [null, null, null, null, null, null, null, null,
    { round: 9, winner: 'CT', players: { E: lateRow(0, 0, 0, 0, false) } },
    { round: 10, winner: 'T', players: { E: lateRow(0, 0, 0, 0, false) } }],
  isReversed: false,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 10,
  scoreboard: { E: { kills: 1, deaths: 1, assists: 0 } }
})
assert.equal(partialKast.E.kastRounds, 9)

// 一回合都没记到：只能用计分板，伤害按游戏里的 ADR 估算
const absent = player('D', 'T')
absent.state.adr = 75
const blind = buildMapPlayerStats({
  players: [absent],
  rounds: [],
  isReversed: false,
  ctId: 'right',
  tId: 'left',
  fallbackRounds: 10,
  scoreboard: { D: { kills: 3, deaths: 4, assists: 2 } }
})
assert.deepEqual(
  [blind.D.kills, blind.D.deaths, blind.D.assists, blind.D.damage, blind.D.kastRounds],
  [3, 4, 2, 750, 6]
)
assert.equal(blind.D.roundsRecorded, 0)
assert.equal(blind.D.impact, 0.31)
assert.equal(blind.D.rating, 0.81)

console.log('实时统计测试通过：快照首杀顺序、真实击杀优先、终场 KDA、伤害估值和网站 Rating 口径均正确。')
