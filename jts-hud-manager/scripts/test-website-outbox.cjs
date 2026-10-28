// 单图结果待上传队列：软件重启后还没重新同步时也要入队、带上这场比赛的固定会话编号；
// 网站说“比赛已结束或取消”时不再重试实时数据。直接编译正式代码里的函数来测，不另写一份。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const filename = path.resolve(__dirname, '../src/main/server/integrations/80gotv.ts')
const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true)
const wanted = ['WebsiteHttpError', 'isClosedMatchError', 'readSelectedMatchId', 'websiteMatchIdFromLocal', 'queueWebsiteMapResult']
const pieces = {}
source.forEachChild((node) => {
  if (ts.isClassDeclaration(node) && wanted.includes(node.name?.getText(source))) {
    pieces[node.name.getText(source)] = node.getText(source)
  }
  if (!ts.isVariableStatement(node)) return
  for (const declaration of node.declarationList.declarations) {
    const name = declaration.name.getText(source)
    if (wanted.includes(name)) pieces[name] = `const ${declaration.getText(source)}`
  }
})
for (const name of wanted) assert.ok(pieces[name], `找不到 ${name}`)

const savedRows = []
const context = vm.createContext({
  status: { forwardTargetMatchId: null, sessionId: null, frameSeq: 0, forwardGeneration: 3, pendingResults: 0 },
  resultQueue: [],
  resultTimer: null,
  setTimeout: () => 1,
  flushMapResults: () => undefined,
  dbRun: async (sql, params) => savedRows.push(params),
  sessionForMatch: async (id) => `80gotv:${id}:stored`,
  Date,
  console
})
const code = ts.transpileModule(
  `${wanted.map((name) => pieces[name]).join('\n')}
   Object.assign(globalThis, { WebsiteHttpError, isClosedMatchError, websiteMatchIdFromLocal, queueWebsiteMapResult })`,
  { compilerOptions: { target: ts.ScriptTarget.ES2022 } }
).outputText
vm.runInContext(code, context)

const run = async () => {
  // 软件重启后还没重新同步（没有上传目标）：按本地比赛编号找回网站比赛 12，结果照样入队
  const started = Date.now()
  await context.queueWebsiteMapResult({ map_name: 'de_nuke', team1_score: 13, team2_score: 9, players: [] }, '80gotv-match-12')
  assert.equal(context.resultQueue.length, 1)
  const entry = context.resultQueue[0]
  assert.equal(entry.matchId, 12)
  assert.equal(entry.payload.session_id, '80gotv:12:stored')
  assert.ok(entry.payload.frame_seq >= started)
  assert.equal(savedRows.length, 1)

  // 同一张图再结算一次：替换原来那条（同一个结算编号），不会多出一条
  await context.queueWebsiteMapResult({ map_name: 'de_nuke', team1_score: 13, team2_score: 10, players: [] }, '80gotv-match-12')
  assert.equal(context.resultQueue.length, 1)
  assert.equal(context.resultQueue[0].resultId, entry.resultId)
  assert.equal(context.resultQueue[0].payload.team2_score, 10)

  // 不是从网站同步来的本地比赛：不上传
  await context.queueWebsiteMapResult({ map_name: 'de_inferno', players: [] }, 'manual-match')
  assert.equal(context.resultQueue.length, 1)

  // 正在上传的那场：用当前会话编号
  context.status.forwardTargetMatchId = 15
  context.status.sessionId = '80gotv:15:live'
  await context.queueWebsiteMapResult({ map_name: 'de_mirage', players: [] }, '80gotv-match-15')
  assert.equal(context.resultQueue[1].payload.session_id, '80gotv:15:live')

  // 网站说比赛已结束或取消（409）才停止重试；其他错误照常重试
  assert.equal(context.websiteMatchIdFromLocal('80gotv-match-0'), null)
  assert.equal(context.isClosedMatchError(new context.WebsiteHttpError('比赛已结束或取消，拒绝覆盖直播数据（/api）', 409)), true)
  assert.equal(context.isClosedMatchError(new context.WebsiteHttpError('较旧实时帧被拒绝（/api）', 409)), false)
  assert.equal(context.isClosedMatchError(new context.WebsiteHttpError('比赛已结束（/api）', 500)), false)
  console.log('单图结果待上传队列检查通过：重启后未同步也入队并带固定会话编号，重复结算会替换，比赛结束不再重试。')
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
