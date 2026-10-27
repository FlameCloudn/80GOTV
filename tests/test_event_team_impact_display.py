"""2026-10-27：赛事数据页的队伍（临时组队也显示）、Impact 最低为 0、单日赛事只写一天。"""

import json
import unittest

from tests.test_broadcast_map_result import BroadcastMapResultTests
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat
from utils.filters import date_range_display_filter
from utils.stats_calc import calculate_rating, estimate_hltv2_impact, non_negative_impact


class ImpactFloorTests(unittest.TestCase):
    def test_shown_impact_never_goes_below_zero(self):
        # 0 杀 0 助攻：回归公式是 -0.41，保存和展示记 0；正常值不变；没有数据仍是“没有”
        self.assertAlmostEqual(estimate_hltv2_impact(0, 0, 20), -0.41)
        self.assertEqual(non_negative_impact(estimate_hltv2_impact(0, 0, 20)), 0.0)
        self.assertAlmostEqual(non_negative_impact(estimate_hltv2_impact(20, 6, 20)), 1.846)
        self.assertIsNone(non_negative_impact(None))


class DateRangeTests(unittest.TestCase):
    def test_single_day_events_show_one_date(self):
        self.assertEqual(date_range_display_filter("2026-05-02", "2026-05-02"), "2026年5月2日")
        self.assertEqual(
            date_range_display_filter("2026-05-02 10:00", "2026-05-02 22:00"), "2026年5月2日"
        )
        self.assertEqual(
            date_range_display_filter("2026-05-02", "2026-05-04"), "2026年5月2日 ~ 2026年5月4日"
        )
        self.assertEqual(date_range_display_filter("2026-05-02", None), "2026年5月2日")
        self.assertEqual(date_range_display_filter(None, "2026-05-04"), "2026年5月4日")
        self.assertEqual(date_range_display_filter(None, None), "")


class EventStatsTemporaryTeamTests(StatsDatabaseCase):
    def setUp(self):
        super().setUp()
        conn = self.conn
        self.temp_event = conn.execute(
            "INSERT INTO events(name, start_date, end_date) VALUES('Temp Cup', '2026-05-02', '2026-05-02')"
        ).lastrowid
        self.p3 = conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES('Temp Three', '333')"
        ).lastrowid
        self.p4 = conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES('Temp Four', '444')"
        ).lastrowid
        snapshot = {
            "version": 1,
            "teams": {
                "1": {"name": "Team 3", "players": [self.p3], "team_id": -1},
                "2": {"name": "Team 4", "players": [self.p4], "team_id": -2},
            },
        }
        # 正式数据里临时队伍就是 team1_id=-1 / team2_id=-2（外键对不上），照旧关掉外键检查再造这场比赛
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        self.temp_match = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, team1_players, team2_players,
                   roster_snapshot, status, bo_format, team1_score, team2_score, map1, map2)
               VALUES(?, -1, -2, ?, ?, ?, 'completed', 'BO3', 2, 0, 'Mirage', 'Inferno')""",
            (self.temp_event, json.dumps([self.p3]), json.dumps([self.p4]), json.dumps(snapshot)),
        ).lastrowid
        for player, side, impact in ((self.p3, "t1", 1.2), (self.p4, "t2", -0.2)):
            add_stat(
                conn,
                self.temp_match,
                player,
                None,
                "Mirage",
                match_team_side=side,
                kills=10,
                deaths=10,
                rounds_played=20,
                rating=1.0,
                impact=impact,
            )
        conn.commit()

    def page(self):
        from app import app

        return app.test_client().get(f"/events/{self.temp_event}/stats").get_data(as_text=True)

    def test_temporary_teams_show_in_player_and_team_rankings(self):
        html = self.page()
        self.assertIn('<td class="muted-cell" data-i18n-ignore>Team 3</td>', html)
        self.assertIn('<td class="muted-cell" data-i18n-ignore>Team 4</td>', html)
        self.assertIn("队伍排名", html)
        self.assertIn("<td><b data-i18n-ignore>Team 3</b></td>", html)
        self.assertIn("<td><b data-i18n-ignore>Team 4</b></td>", html)

    def test_single_day_event_and_two_decimal_impact(self):
        html = self.page()
        self.assertIn("<span>2026年5月2日</span>", html)
        self.assertNotIn("2026年5月2日 ~", html)
        self.assertIn('data-val="1.2">1.20</td>', html)

    def test_stored_negative_impact_is_raised_to_zero_without_touching_rating(self):
        from models import get_db, init_tables

        init_tables()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT impact, rating FROM match_stats WHERE player_id=?", (self.p4,)
            ).fetchone()
            summary = conn.execute(
                "SELECT avg_impact FROM player_performance_summary WHERE player_id=?", (self.p4,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual((row["impact"], row["rating"]), (0, 1.0))
        self.assertEqual(summary["avg_impact"], 0)
        self.assertIn('data-val="0.0">0.00</td>', self.page())


class LiveImpactFloorTests(unittest.TestCase):
    # 借用直播上报测试的准备步骤（独立临时数据库），不重复跑那一批测试
    setUp = BroadcastMapResultTests.setUp
    tearDown = BroadcastMapResultTests.tearDown
    _player = staticmethod(BroadcastMapResultTests._player)
    _payload = BroadcastMapResultTests._payload
    _post = BroadcastMapResultTests._post

    def test_low_kill_player_saves_zero_impact_but_rating_uses_the_formula(self):
        low = self._player("222", "Aurora", "team2", 2, 16, 300)
        low.update(
            assists=0,
            headshots=1,
            kastRounds=6,
            firstKills=0,
            firstDeaths=2,
            multi1k=2,
            multi2k=0,
            multi3k=0,
            clutchesWon=0,
            clutch1v1=0,
            tradeKills=0,
            tradeDeaths=2,
            mvpCount=0,
            utilityDamage=20,
            bombPlants=0,
            bombDefuses=0,
            flashAssists=0,
            tStats={"kills": 1, "deaths": 8, "adr": 15.0, "rating": 0.2},
            ctStats={"kills": 1, "deaths": 8, "adr": 15.0, "rating": 0.2},
        )
        payload = self._payload()
        payload["players"][1] = low
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        from models import get_db

        conn = get_db()
        row = conn.execute(
            "SELECT impact, rating FROM match_stats WHERE player_id=?", (self.player2_id,)
        ).fetchone()
        conn.close()
        raw = estimate_hltv2_impact(2, 0, 20)
        self.assertLess(raw, 0)
        self.assertEqual(row["impact"], 0)
        expected_rating, _, _ = calculate_rating(2, 16, 20, adr=15.0, kast=30.0, impact=raw)
        self.assertAlmostEqual(row["rating"], expected_rating)


del BroadcastMapResultTests, StatsDatabaseCase


if __name__ == "__main__":
    unittest.main()
