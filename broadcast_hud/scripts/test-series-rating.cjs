const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')

const sourcePath = path.resolve(__dirname, '../src/HUD/VictoryShowcase/series-rating.ts')
const source = fs.readFileSync(sourcePath, 'utf8')
const ts = require(require.resolve('typescript', {
  paths: [path.resolve(__dirname, '../../jts-hud-manager')]
}))
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

const { mapRating, weightedSeriesRating } = compiled.exports

// A real zero from the server is valid data and must not be replaced by an estimate.
assert.equal(mapRating({
  rating: 0,
  kills: 9,
  deaths: 1,
  assists: 3,
  adr: 150,
  roundsPlayed: 20
}), 0)

// Missing ratings use the same Rating 2.0 regression as the website.
assert.equal(mapRating({
  kills: 4,
  deaths: 2,
  assists: 1,
  adr: 100,
  roundsPlayed: 10
}), 1.21)
assert.equal(mapRating({
  kills: 0,
  deaths: 0,
  assists: 0,
  adr: 0,
  roundsPlayed: 16
}), 0.79)

// Series rating is the round-weighted average of each map's already-calculated rating.
assert.equal(weightedSeriesRating([
  { rating: 0, rounds: 10 },
  { rating: 1.5, rounds: 30 }
]), 1.13)

console.log('HUD 评分测试通过：合法零分、缺失评分估值和系列回合加权均正确。')
