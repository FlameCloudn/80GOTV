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
const status = { forwardGeneration: 1, forwardTargetMatchId: 7, sessionId: 'active-session', frameSeq: 42 }
const context = vm.createContext({
  status, pendingPayload: {}, resultQueue: [], forwardAttempts: 3,
  forwardTimer: null, clearTimeout, Date
})
const code = ts.transpileModule(`const ${resetFunction}; globalThis.reset = resetForwardTarget`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 }
}).outputText
vm.runInContext(code, context)

context.reset(7)
assert.equal(status.sessionId, 'active-session')
assert.equal(status.frameSeq, 42)
assert.equal(status.forwardGeneration, 2)
assert.equal(context.pendingPayload, null)

context.reset(8)
assert.match(status.sessionId, /^80gotv:8:/)
assert.equal(status.frameSeq, 0)
context.reset(null)
assert.equal(status.sessionId, null)
assert.equal(status.forwardTargetMatchId, null)
console.log('导播连接编号检查通过：同场同步保留编号，换场和取消同步重置编号。')
