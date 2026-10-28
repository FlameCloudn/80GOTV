// 给“独立数据目录里的测试导播软件”喂一份假的 CS2 实时数据（只发到本机测试端口，不碰网站）
// 用本机数据库里已有的选手名字（前 10 人），5 个 CT、5 个 T
const PLAYER_FALLBACK = ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf', 'Hotel', 'India', 'Juliet']

const makePlayer = (name, index, side) => ({
  name,
  observer_slot: (index + 1) % 10,
  team: side,
  state: { health: 100 - index * 7, armor: 100, helmet: true, flashed: 0, smoked: 0, burning: 0, money: 3200 + index * 250, round_kills: 0, round_killhs: 0, round_totaldmg: 0, equip_value: 4100 },
  match_stats: { kills: 14 - index, assists: index % 4, deaths: 8 + (index % 5), mvps: 1, score: 30 - index },
  weapons: {
    weapon_0: { name: 'weapon_knife', paintkit: 'default', type: 'Knife', state: 'holstered' },
    weapon_1: { name: side === 'CT' ? 'weapon_m4a1_silencer' : 'weapon_ak47', paintkit: 'default', type: 'Rifle', ammo_clip: 25, ammo_clip_max: 30, ammo_reserve: 75, state: 'active' }
  },
  position: `${-1200 + index * 90}.00, ${300 + index * 40}.00, 120.00`,
  forward: '0.70, 0.70, 0.00'
})

const buildPayload = (roster) => {
  const allplayers = {}
  roster.forEach((player, index) => {
    allplayers[player.steamid] = makePlayer(player.name, index, index < 5 ? 'CT' : 'T')
  })
  const first = roster[0]
  return {
    provider: { name: 'Counter-Strike 2', appid: 730, version: 14000, steamid: '76561198000000999', timestamp: Math.floor(Date.now() / 1000) },
    map: {
      mode: 'competitive', name: 'de_inferno', phase: 'live', round: 12,
      team_ct: { score: 7, consecutive_round_losses: 0, timeouts_remaining: 1, matches_won_this_series: 0 },
      team_t: { score: 5, consecutive_round_losses: 1, timeouts_remaining: 1, matches_won_this_series: 0 },
      num_matches_to_win_series: 0, round_wins: {}
    },
    round: { phase: 'live' },
    player: { steamid: first.steamid, name: first.name, observer_slot: 1, team: 'CT', activity: 'playing', state: allplayers[first.steamid].state, match_stats: allplayers[first.steamid].match_stats, weapons: allplayers[first.steamid].weapons, position: allplayers[first.steamid].position, forward: allplayers[first.steamid].forward },
    allplayers,
    phase_countdowns: { phase: 'live', phase_ends_in: '84.3' },
    grenades: {},
    bomb: { state: 'carried', position: '0.00, 0.00, 0.00', player: roster[5].steamid }
  }
}

const loadRoster = async (apiBase) => {
  try {
    const players = await (await fetch(`${apiBase}/players`)).json()
    const real = players.filter((p) => /^\d{17}$/.test(String(p.steamid || '')) && !p.isCoach).slice(0, 10)
    if (real.length === 10) return real.map((p) => ({ steamid: p.steamid, name: p.username || p.steamid }))
  } catch {
    // 读不到就用假名字
  }
  return PLAYER_FALLBACK.map((name, index) => ({ steamid: `7656119800000${String(index).padStart(4, '0')}`, name }))
}

// 每秒发一次，返回停止函数
module.exports.startFeed = async (apiBase, gsiBase) => {
  const roster = await loadRoster(apiBase)
  const send = () =>
    fetch(`${gsiBase}/cs2/input`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildPayload(roster)) })
      .then((response) => response.status)
      .catch((error) => `发送失败 ${error.message}`)
  console.log('假数据第一次发送：', await send())
  const timer = setInterval(send, 1000)
  return () => clearInterval(timer)
}
