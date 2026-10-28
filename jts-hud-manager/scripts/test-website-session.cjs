const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

// Compile the production reset function with its state dependencies, not a copied implementation.
const filename = path.resolve(__dirname, '../src/main/server/integrations/80gotv.ts')
const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true)
let resetFunction
source.forEachChild(node => {
  if (!ts.isVariableStatement(node)) return
  for (const declaration of node.declarationList.declarations) {
    if (declaration.name.getText(source) === 'resetForwardTarget') resetFunction = declaration.getText(source)
  }
})
assert.ok(resetFunction)
const status = {
  forwardGeneration: 1, forwardTargetMatchId: 7, sessionId: 'active-session', frameSeq: 42, forwardClosedMatchId: 7
}
const context = vm.createContext({
  status, pendingPayload: {}, resultQueue: [{ matchId: 9, generation: 0 }], forwardAttempts: 3,
  forwardTimer: null, clearTimeout, Date
})
const code = ts.transpileModule(`const ${resetFunction}; globalThis.reset = resetForwardTarget`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 }
}).outputText
vm.runInContext(code, context)

// 同一场比赛重新同步：沿用原来的会话编号和帧编号，并解除“比赛已结束，停止上传”的标记
context.reset(7, '80gotv:7:stored')
assert.equal(status.sessionId, 'active-session')
assert.equal(status.frameSeq, 42)
assert.equal(status.forwardGeneration, 2)
assert.equal(status.forwardClosedMatchId, null)
assert.equal(context.pendingPayload, null)

// 换一场比赛：用这场比赛在本机存下的固定会话编号；帧编号从当前时间（毫秒）起算，重启后也比之前的大
const before = Date.now()
context.reset(9, '80gotv:9:stored')
assert.equal(status.sessionId, '80gotv:9:stored')
assert.ok(status.frameSeq >= before)
// 这场比赛排队中的单图结果跟着换到新的批次，可以继续上传
assert.equal(context.resultQueue[0].generation, status.forwardGeneration)

// 没有存过编号时临时生成一个；取消同步时清空
context.reset(8)
assert.match(status.sessionId, /^80gotv:8:/)
context.reset(null)
assert.equal(status.sessionId, null)
assert.equal(status.forwardTargetMatchId, null)
assert.equal(status.frameSeq, 0)
console.log('导播连接编号检查通过：同场同步保留编号，换场用本机固定编号，帧编号随时间递增，取消同步清空。')
