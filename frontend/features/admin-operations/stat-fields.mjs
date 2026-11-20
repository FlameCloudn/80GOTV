import { message as siteMessage } from '../../shared/i18n.js';
export var STAT_GROUPS = [
  {
    title: siteMessage('client.ops_stat-fields.core_performance'),
    fields: [
      ['rounds_played', siteMessage('client.ops_stat-fields.rounds_played')],
      ['kills', siteMessage('client.ops_stat-fields.kills')],
      ['deaths', siteMessage('client.ops_stat-fields.deaths')],
      ['assists', siteMessage('client.ops_stat-fields.assists')],
      ['damage', siteMessage('client.ops_stat-fields.total_damage')],
      ['adr', 'ADR'],
      ['kast', 'KAST (%)'],
      ['kast_rounds', siteMessage('client.ops_stat-fields.kast_rounds')],
      ['impact', 'Impact'],
      ['rating_impact', 'Rating Impact'],
      ['rating', 'Rating 2.0'],
      ['rws_basic', 'RWS'],
      ['damage_delta_per_round', siteMessage('client.ops_stat-fields.damage_diff_round')]
    ]
  },
  {
    title: siteMessage('client.ops_stat-fields.openings_duels'),
    fields: [
      ['headshot_kills', siteMessage('client.ops_stat-fields.headshot_kills')],
      ['headshot_percentage', siteMessage('client.ops_stat-fields.headshot')],
      ['first_kills', siteMessage('client.ops_stat-fields.opening_kills')],
      ['first_deaths', siteMessage('client.ops_stat-fields.opening_deaths')],
      ['trade_kills', siteMessage('client.ops_stat-fields.trade_kills')],
      ['trade_deaths', siteMessage('client.ops_stat-fields.traded_deaths')],
      ['mvp_count', siteMessage('client.ops_stat-fields.round_mvps')]
    ]
  },
  {
    title: siteMessage('client.ops_stat-fields.multi_kills_clutches'),
    fields: [
      ['multi1k', '1K'],
      ['multi2k', '2K'],
      ['multi3k', '3K'],
      ['multi4k', '4K'],
      ['multi5k', '5K'],
      ['clutches_won', siteMessage('client.ops_stat-fields.clutches_won')],
      ['clutch_1v1', '1v1'],
      ['clutch_1v2', '1v2'],
      ['clutch_1v3', '1v3'],
      ['clutch_1v4', '1v4'],
      ['clutch_1v5', '1v5']
    ]
  },
  {
    title: siteMessage('client.ops_stat-fields.utility_objectives'),
    fields: [
      ['utility_damage', siteMessage('client.ops_stat-fields.utility_damage')],
      ['utility_damage_per_round', siteMessage('client.ops_stat-fields.utility_damage_round')],
      ['enemies_flashed', siteMessage('client.ops_stat-fields.enemies_flashed')],
      ['flash_assists', siteMessage('client.ops_stat-fields.flash_assists')],
      ['flash_count', siteMessage('client.ops_stat-fields.flashes_thrown')],
      ['flash_enemy_seconds', siteMessage('client.ops_stat-fields.enemy_blind_duration_s')],
      ['flash_blinded_seconds', siteMessage('client.ops_stat-fields.self_blind_duration_s')],
      ['he_count', siteMessage('client.ops_stat-fields.he_grenades')],
      ['smoke_count', siteMessage('client.ops_stat-fields.smokes')],
      ['molotov_count', siteMessage('client.ops_stat-fields.molotovs_incendiaries')],
      ['bomb_plants', siteMessage('client.ops_stat-fields.bomb_plants')],
      ['bomb_defuses', siteMessage('client.ops_stat-fields.bomb_defuses')]
    ]
  }
];

export var FIELD_LABELS = {};
STAT_GROUPS.forEach(function (g) {
  g.fields.forEach(function (item) {
    FIELD_LABELS[item[0]] = item[1];
  });
});
