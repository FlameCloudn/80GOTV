const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const filename = path.resolve(__dirname, '../src/main/server/integrations/80gotv.ts')
const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true)
const declarations = new Map()
source.forEachChild((node) => {
  if (ts.isClassDeclaration(node)) declarations.set(node.name?.text, node.getText(source))
  if (ts.isVariableStatement(node)) {
    for (const declaration of node.declarationList.declarations) {
      declarations.set(declaration.name.getText(source), `const ${declaration.getText(source)}`)
    }
  }
})

function load(names, overrides = {}) {
  const sent = [], writes = [], timers = []
  const context = vm.createContext({
    console: { log() {}, warn() {} },
    Date, resultQueue: [], resultTimer: null, resultForwarding: false,
    pendingPayload: null, forwardTimer: null, forwardAttempts: 0,
    status: { forwardTargetMatchId: 7, importedMatchId: 7, sessionId: 'session-7', forwardGeneration: 3, frameSeq: 1 },
    getSettings: async () => ({ websiteUrl: 'http://127.0.0.1', websiteMatchId: '7', websiteGsiToken: 'local-test-placeholder', forwardLiveData: false }),
    loadResultOutbox: async () => {}, normalizeWebsiteUrl: value => value,
    dbReady: Promise.resolve(),
    sessionForMatch: async id => `session-${id}`, teamId: (_team, side) => `team-${side}`,
    dbRun: async (sql, params) => { writes.push({ sql, params }) },
    fetchJson: async (url, options) => { const payload = JSON.parse(options.body); sent.push(payload); return { ok: true, match_id: 7, map_name: payload.map_name, result_id: payload.result_id } },
    setTimeout: (callback, delay) => { timers.push({ callback, delay }); return timers.length },
    clearTimeout() {}, flushMapResults: async () => {},
    ...overrides
  })
  const text = names.map(name => { assert.ok(declarations.has(name), `找不到正式函数 ${name}`); return declarations.get(name) }).join('\n')
  vm.runInContext(ts.transpileModule(`${text}\nObject.assign(globalThis, {${names.join(',')}})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }
  }).outputText, context)
  return { context, sent, writes, timers }
}

const queueNames = ['readSelectedMatchId', 'websiteMatchIdFromLocal', 'queueWebsiteMapResult']
const flushNames = ['WebsiteHttpError', 'readSelectedMatchId', 'mapName', 'scheduleMapResultFlush', 'flushMapResults']
const result = (map, id) => ({ resultId: id, matchId: 7, generation: 3, attempts: 0, payload: { map_name: map, result_id: id } })

async function run() {
  {
    const { context } = load(queueNames)
    await context.queueWebsiteMapResult({ map_name: 'de_nuke' }, '80gotv-match-8')
    assert.equal(context.resultQueue[0].matchId, 8, '赛果必须属于来源比赛，而不是当前上传目标')
    await context.queueWebsiteMapResult({ map_name: 'de_mirage' }, 'manual-match')
    assert.equal(context.resultQueue.length, 1, '手工比赛不得混入网站赛果')
  }
  {
    const { context } = load(flushNames, { fetchJson: async () => ({ ok: true, match_id: 999, map_name: 'de_nuke' }) })
    context.resultQueue.push(result('de_nuke', 'wrong-receipt'))
    await context.flushMapResults()
    assert.equal(context.resultQueue.length, 1, '错误比赛回执不能清掉待上传原件')
  }
  {
    const { context } = load(flushNames, { fetchJson: async () => ({ ok: true, match_id: 7, map_name: 'de_nuke', map_slot: 2 }) })
    const entry = result('de_nuke', 'wrong-slot')
    entry.payload.map_slot = 1
    context.resultQueue.push(entry)
    await context.flushMapResults()
    assert.equal(context.resultQueue.length, 1, '同名地图错误槽位回执也不得清理')
  }
  {
    const sent = []
    const { context } = load(flushNames, { fetchJson: async (_url, options) => {
      const payload = JSON.parse(options.body); sent.push(payload.map_name)
      if (payload.map_name === 'de_nuke') throw new context.WebsiteHttpError('旧结算被拒绝', 409)
      return { ok: true, match_id: 7, map_name: payload.map_name, result_id: payload.result_id }
    } })
    context.resultQueue.push(result('de_nuke', 'rejected'), result('de_mirage', 'valid'))
    await context.flushMapResults()
    await context.flushMapResults()
    assert.deepEqual(sent, ['de_nuke', 'de_mirage'], '明确失败的图一不得阻塞图二')
    assert.equal(context.resultQueue.length, 1)
  }
  {
    const { context, sent } = load(flushNames)
    context.resultQueue.push(result('de_nuke', 'live-disabled'))
    await context.flushMapResults()
    assert.equal(sent.length, 1, '关闭实时上传不应停止地图结算')
    assert.equal(context.resultQueue.length, 0)
  }
  {
    let finish
    const { context } = load([...new Set([...queueNames, ...flushNames])], {
      fetchJson: (_url, options) => new Promise(resolve => {
        const payload = JSON.parse(options.body)
        finish = () => resolve({ ok: true, match_id: 7, map_name: payload.map_name, result_id: payload.result_id })
      })
    })
    await context.queueWebsiteMapResult({ map_name: 'de_nuke', team2_score: 9 }, '80gotv-match-7')
    const firstId = context.resultQueue[0].resultId
    const flushing = context.flushMapResults()
    while (!finish) await Promise.resolve()
    await context.queueWebsiteMapResult({ map_name: 'de_nuke', team2_score: 10 }, '80gotv-match-7')
    assert.equal(context.resultQueue.length, 2, '正在传送的旧内容不能原地替换')
    assert.notEqual(context.resultQueue[1].resultId, firstId)
    finish()
    await flushing
    assert.equal(context.resultQueue.length, 1)
    assert.equal(context.resultQueue[0].payload.team2_score, 10, '旧回执不得删除修正后的新结果')
  }
  {
    const { context } = load(['mapName', 'buildVetos', 'mergeWebsiteVetos'])
    const match = { team1: {}, team2: {}, maps: [{ slot: 1, name: 'Nuke', team1_score: 6, team2_score: 5, map_finished: false }] }
    const incoming = context.buildVetos(match)
    assert.equal(incoming[0].mapEnd, false, '非零比分不代表地图结束')
    assert.equal(incoming[0].mapSlot, 1)
    const old = { ...incoming[0], mapGeneration: 2, rounds: [{ round: 1 }], playerStats: { p: { kills: 1 } } }
    const merged = context.mergeWebsiteVetos([old], incoming)
    assert.equal(merged[0].rounds.length, 1)
    assert.equal(merged[0].mapGeneration, 2)
    assert.equal(merged[0].playerStats.p.kills, 1)
    assert.equal(context.mergeWebsiteVetos([{ ...old, mapSlot: 2 }], incoming)[0].rounds.length, 0, '不同地图槽位不得继承旧回合')
  }
  {
    const { context } = load(['listWebsiteSources'], { fetchJson: async url => url.endsWith('/events') ? { events: [] } : { matches: [
      { id: 1, status: 'completed', match_time: '2020-01-01', team1: {}, team2: {}, event: {} },
      { id: 3, status: 'upcoming', match_time: '2020-01-01', team1: {}, team2: {}, event: {} },
      { id: 2, status: 'upcoming', match_time: '2030-01-01', team1: {}, team2: {}, event: {} }
    ] } })
    assert.equal((await context.listWebsiteSources())[0].id, 2, '默认应先选择即将进行的比赛')
  }
  {
    let refreshes = 0
    const previous = [{ mapName: 'de_nuke', mapSlot: 1, mapGeneration: 2, type: 'pick', rounds: [{ round: 1 }], playerStats: { p: { kills: 1 } } }]
    const { context, writes } = load(['mapName', 'buildVetos', 'mergeWebsiteVetos', 'syncWebsiteMatch'], {
      fetchJson: async () => ({ ok: true, match: { id: 7, bo: 'BO3', team1: { name: '甲', players: [] }, team2: { name: '乙', players: [] }, maps: [{ slot: 1, name: 'Nuke', team1_score: 6, team2_score: 5, map_finished: false }] } }),
      dbGet: async () => ({ vetos: JSON.stringify(previous) }),
      fillMatchLogosFromEvent: async (_url, match) => match,
      upsertTeam: async (_url, _team, side) => `team-${side}`,
      upsertPlayer: async () => {}, websitePlayerPresentation: new Map(),
      matchId: id => `80gotv-match-${id}`, syncHudWebsiteConfig: async () => {},
      writeSettingValue: async () => {}, resetForwardTarget() {},
      refreshGsiMatchContext: async () => { refreshes++ }
    })
    await context.syncWebsiteMatch('7')
    const saved = JSON.parse(writes.find(row => row.sql.includes('INSERT INTO matches')).params[6])
    assert.equal(saved[0].rounds.length, 1, '完整同步也必须保留已录回合')
    assert.equal(saved[0].playerStats.p.kills, 1)
    assert.equal(saved[0].mapGeneration, 2)
    assert.equal(refreshes, 1, '同步完成必须立即刷新游戏队伍缓存')
  }
  console.log('网站联动回归通过：来源比赛、回执核对、独立补传、上传开关、地图确认、同场数据保留和默认排序。')
}

run().catch(error => { console.error('网站联动回归失败：' + error.message); process.exitCode = 1 })
