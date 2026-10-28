const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { execFileSync } = require('node:child_process')
const { _electron: electron } = require('playwright')

const appDir = path.resolve(__dirname, '..')
const candidateRoot = path.resolve(appDir, '..')
const candidateParent = path.resolve(candidateRoot, '..')
const root = fs.existsSync(path.join(candidateParent, 'docs', 'CODEX_PROJECT_MEMORY.md'))
  ? candidateParent
  : candidateRoot
const output = path.join(root, 'output/director-fix-tests')
const userData = path.join(output, `runtime-user-${Date.now()}`)
const api = 'http://127.0.0.1:15491/api'
const executablePath = process.argv[2] && path.resolve(process.argv[2])
const roster = Array.from({ length: 10 }, (_, index) => ({
  id: index + 1, slot: index % 5 + 1, nickname: `Test ${index + 1}`,
  steam_id: `7656119800000${String(index).padStart(4, '0')}`, avatar: '/avatar.png'
}))
const match = {
  id: 7, status: 'live', event: { id: null, name: '本地测试', short_name: 'TEST' },
  stage: '测试', bo: 'BO3', match_time: '2026-10-28T20:00:00',
  team1: { id: 1, name: 'Test Alpha', short_name: 'ALP', logo: '', series_score: 0, players: roster.slice(0, 5) },
  team2: { id: 2, name: 'Test Bravo', short_name: 'BRV', logo: '', series_score: 0, players: roster.slice(5) },
  maps: [{ slot: 1, name: 'de_inferno', team1_score: 0, team2_score: 0, picked_by: 't1', opening_ct_team: 't1', opening_side_source: 'website_bp', map_finished: false }],
  bp: { status: 'completed', picks: [{ map: 'Inferno', picked_by: 't1', side: 'T', side_team: 't2' }] },
  roster_locked: true, roster_issues: [], ready_for_start: true
}
let app, feedTimer, mock, control
let map = 'de_inferno', sequence = 0, paused = false
let liveRequests = 0, resultRequests = 0
const avatar = fs.readFileSync(path.join(appDir, 'resources/map-radars/de_inferno.png'))

function payload() {
  const allplayers = {}
  roster.forEach((player, index) => {
    const team = index < 5 ? 'CT' : 'T'
    const offset = index % 5 * 40
    const xy = map === 'de_nuke' ? [500 + offset, -1000 + offset]
      : map === 'de_vertigo' ? [-1500 + offset, -600 + offset]
        : map === 'de_overpass' ? [-2500 + offset, 500 + offset]
          : map === 'de_train' ? [-600 + offset, -500 + offset]
            : [-1200 + index * 180, 300 + index * 150]
    allplayers[player.steam_id] = {
      name: player.nickname, observer_slot: index, team,
      state: { health: 100, armor: 100, helmet: true, flashed: 0, smoked: 0, burning: 0, money: 3200, round_kills: 0, round_killhs: 0, round_totaldmg: 100, equip_value: 4100 },
      match_stats: { kills: 14 - index, assists: 2, deaths: 8, mvps: 1, score: 30 },
      weapons: { weapon_0: { name: 'weapon_knife', paintkit: 'default', type: 'Knife', state: 'holstered' }, weapon_1: { name: team === 'CT' ? 'weapon_m4a1_silencer' : 'weapon_ak47', paintkit: 'default', type: 'Rifle', ammo_clip: 25, ammo_clip_max: 30, ammo_reserve: 75, state: 'active' } },
      position: `${xy[0]}, ${xy[1]}, ${map === 'de_nuke' ? (index < 5 ? -200 : -700) : map === 'de_vertigo' ? (index < 5 ? 12000 : 11000) : 120}`,
      forward: '0.70, 0.70, 0'
    }
  })
  const steamid = roster[0].steam_id
  return {
    provider: { name: 'Counter-Strike 2', appid: 730, version: 14000, steamid, timestamp: Math.floor(Date.now() / 1000) },
    map: { mode: 'competitive', name: map, phase: 'live', round: 12,
      team_ct: { score: 7, consecutive_round_losses: 0, timeouts_remaining: 1, matches_won_this_series: 0 },
      team_t: { score: 5, consecutive_round_losses: 1, timeouts_remaining: 1, matches_won_this_series: 0 }, num_matches_to_win_series: 0, round_wins: {} },
    round: { phase: 'live' }, player: { steamid, ...allplayers[steamid], activity: 'playing' }, allplayers,
    phase_countdowns: { phase: 'live', phase_ends_in: String(85 - sequence++ % 10) },
    grenades: {}, bomb: { state: 'carried', position: '0, 0, 0', player: roster[5].steam_id }
  }
}

async function send() {
  if (paused) return
  const response = await fetch('http://127.0.0.1:15492/cs2/input', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) })
  if (!response.ok) throw new Error(`模拟游戏数据被拒绝：${response.status}`)
}

const listen = (server, port) => new Promise((resolve, reject) => server.once('error', reject).listen(port, '127.0.0.1', resolve))
const json = (res, data) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)) }
async function stop() {
  clearInterval(feedTimer)
  control?.close()
  mock?.close()
  await app?.close()
  console.log(`本地验证已关闭；实时请求 ${liveRequests} 次，地图结果 ${resultRequests} 次。`)
}

async function run() {
  fs.mkdirSync(path.join(userData, 'database'), { recursive: true })
  execFileSync('python', ['-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)"); c.execute("INSERT INTO settings VALUES(?,?)",("websiteUrl","http://127.0.0.1:15493")); c.commit(); c.close()', path.join(userData, 'database/jts-hud-manager.sqlite')])
  mock = http.createServer(async (req, res) => {
    if (req.url === '/avatar.png') { res.writeHead(200, { 'Content-Type': 'image/png' }); return res.end(avatar) }
    if (req.url === '/api/broadcast/matches') return json(res, { ok: true, matches: [match] })
    if (req.url === '/api/broadcast/events') return json(res, { ok: true, events: [] })
    if (req.url === '/api/broadcast/matches/7') return json(res, { ok: true, match })
    if (req.url.endsWith('/connection-test')) return json(res, { ok: true, match_id: 7, team1_name: match.team1.name, team2_name: match.team2.name })
    let body = ''
    for await (const chunk of req) body += chunk
    if (req.url.endsWith('/live')) { liveRequests++; return json(res, { ok: true, match_id: 7 }) }
    if (req.url.endsWith('/map-result')) { resultRequests++; const value = JSON.parse(body); return json(res, { ok: true, match_id: 7, map_name: value.map_name, map_slot: value.map_slot, result_id: value.result_id, applied: true }) }
    res.writeHead(404); res.end('{}')
  })
  await listen(mock, 15493)
  app = await electron.launch({
    ...(executablePath ? { executablePath, args: [`--user-data-dir=${userData}`] } : { args: [appDir, `--user-data-dir=${userData}`] }),
    cwd: appDir, env: { ...process.env, HUD_PORT: '15491', GSI_PORT: '15492' }, timeout: 60000
  })
  const page = await app.firstWindow()
  await page.waitForLoadState('domcontentloaded')
  const request = async (url, body) => {
    const response = await fetch(`${api}${url}`, { method: url === '/settings' ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const value = await response.json()
    if (!response.ok || value.ok === false) throw new Error(`本地准备失败：${JSON.stringify(value)}`)
    return value
  }
  await request('/settings', { websiteUrl: 'http://127.0.0.1:15493', websiteGsiToken: 'local-runtime-placeholder', websiteMatchId: '7', forwardLiveData: false })
  await request('/80gotv/sync', { matchId: '7' })
  await send()
  feedTimer = setInterval(() => send().catch(error => console.error(error.message)), 500)
  fs.mkdirSync(path.join(root, 'output/ui-audit/director-fix'), { recursive: true })
  await page.screenshot({ path: path.join(root, 'output/ui-audit/director-fix/desktop-app.png') })
  control = http.createServer(async (req, res) => {
    if (req.url === '/pause') { paused = true; return json(res, { ok: true, paused }) }
    if (req.url === '/resume') { paused = false; await send(); return json(res, { ok: true, paused }) }
    if (req.url === '/finish-swapped') {
      paused = true
      const frame = payload()
      for (const player of Object.values(frame.allplayers)) player.team = player.team === 'CT' ? 'T' : 'CT'
      frame.player.team = frame.allplayers[frame.player.steamid].team
      frame.map.phase = 'gameover'
      frame.map.round = 24
      frame.map.team_ct.score = 13
      frame.map.team_t.score = 11
      frame.map.round_wins = { '23': 'ct_win_elimination' }
      frame.round.phase = 'over'
      frame.round.win_team = 'CT'
      frame.phase_countdowns = { phase: 'gameover', phase_ends_in: '0' }
      const response = await fetch('http://127.0.0.1:15492/cs2/input', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(frame)
      })
      return json(res, { ok: response.ok, status: response.status })
    }
    if (req.url.startsWith('/map/')) {
      map = req.url.slice(5)
      match.maps[0].name = map
      match.bp.picks[0].map = map.slice(3)
      await request('/80gotv/sync', { matchId: '7' })
      await send()
      return json(res, { ok: true, map })
    }
    if (req.url === '/stop') { json(res, { ok: true }); await stop(); return }
    json(res, { ok: true, map, paused, liveRequests, resultRequests })
  })
  await listen(control, 15494)
  console.log('独立测试导播已启动，未使用正式数据。')
  console.log('画面：http://127.0.0.1:15491/huds/default/index.html?isProd=1')
  console.log('控制：http://127.0.0.1:15494/；暂停/pause，恢复/resume，换图/map/de_nuke，关闭/stop。')
}

run().catch(async error => { console.error('本地画面验证失败：' + error.message); await stop(); process.exitCode = 1 })
