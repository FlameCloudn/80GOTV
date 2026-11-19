import json
import unittest
from pathlib import Path
from unittest.mock import patch

from routes.matches import _aggregate_match_rows, _build_match_player_row
from services.demo_service import insert_match_stat
from services.demo_side_backfill import apply_side_backfill, prepare_side_backfill
from tests.test_refactor_stats_consistency import StatsDatabaseCase, add_stat
from utils.demo_parser import parse_player_stats


def side_demo():
    players = {
        "111": ("A1", "A", 2, 1, 1, 200, 1, 0, 1, 100),
        "112": ("A2", "A", 1, 2, 1, 100, 0, 0, 1, 100),
        "221": ("B1", "B", 2, 2, 0, 200, 0, 2, 0, 100),
        "222": ("B2", "B", 1, 1, 0, 100, 0, 0, 0, 50),
    }
    data = {
        "players": {},
        "kills": [],
        "damages": [],
        "playerEconomies": [],
        "playersFlashed": [],
        "rounds": [],
        "teamA": {"name": "A"},
        "teamB": {"name": "B"},
    }
    for sid, (name, team, kills, deaths, assists, damage, hs, fk, fd, kast) in players.items():
        data["players"][sid] = {
            "name": name,
            "team": {"letter": team},
            "killCount": kills,
            "deathCount": deaths,
            "assistCount": assists,
            "healthDamage": damage,
            "headshotCount": hs,
            "firstKillCount": fk,
            "firstDeathCount": fd,
            "kast": kast,
        }
    for number, a_side, winner in ((1, 2, "A"), (2, 3, "B")):
        data["rounds"].append(
            {
                "number": number,
                "teamASide": a_side,
                "teamBSide": 5 - a_side,
                "teamAName": "A",
                "teamBName": "B",
                "winnerName": winner,
                "winnerSide": a_side if winner == "A" else 5 - a_side,
                "startTick": 1 if number == 1 else 101,
                "endTick": number * 100,
            }
        )
        for sid, player in data["players"].items():
            data["playerEconomies"].append(
                {
                    "roundNumber": number,
                    "steamId": sid,
                    "playerSide": a_side if player["team"]["letter"] == "A" else 5 - a_side,
                }
            )
    for number, tick, killer, victim, assister, hs, flash, traded in (
        (1, 10, "221", "112", "", False, False, False),
        (1, 20, "111", "221", "", True, False, True),
        (1, 30, "111", "222", "112", False, True, False),
        (2, 110, "221", "111", "", False, False, False),
        (2, 120, "112", "221", "111", False, False, True),
        (2, 130, "222", "112", "", False, False, False),
    ):
        a_side = 2 if number == 1 else 3
        killer_side = a_side if players[killer][1] == "A" else 5 - a_side
        data["kills"].append(
            {
                "roundNumber": number,
                "tick": tick,
                "killerSteamId": killer,
                "victimSteamId": victim,
                "assisterSteamId": assister,
                "killerSide": killer_side,
                "victimSide": 5 - killer_side,
                "assisterSide": killer_side if assister else 0,
                "isHeadshot": hs,
                "isAssistedFlash": flash,
                "isTradeDeath": traded,
            }
        )
        data["damages"].append(
            {
                "roundNumber": number,
                "tick": tick,
                "attackerSteamId": killer,
                "victimSteamId": victim,
                "attackerSide": killer_side,
                "victimSide": 5 - killer_side,
                "healthDamage": 100,
            }
        )
    data["playersFlashed"].append(
        {
            "roundNumber": 1,
            "tick": 5,
            "flasherSteamId": "112",
            "flashedSteamId": "222",
            "flasherSide": 2,
            "flashedSide": 3,
            "duration": 1.5,
        }
    )
    return data


class DemoSideParsingTests(unittest.TestCase):
    def test_events_follow_t_ct_after_halftime_and_preserve_real_zero(self):
        players = {str(p["steam_id"]): p for p in parse_player_stats(side_demo())}
        a1 = players["111"]["side_stats"]
        self.assertEqual(a1["t"]["kills"], 2)
        self.assertEqual(a1["ct"]["kills"], 0)
        self.assertEqual(a1["ct"]["first_deaths"], 1)
        self.assertEqual(a1["t"]["headshot_kills"], 1)
        self.assertEqual(a1["t"]["clutches_won"], 1)
        self.assertEqual(a1["ct"]["assists"], 1)
        self.assertEqual(a1["t"]["kast"], 100)
        self.assertEqual(a1["ct"]["kast"], 100)
        self.assertEqual(a1["t"]["rws"], 100)
        self.assertEqual(a1["ct"]["rws"], 0)
        self.assertEqual(players["112"]["side_stats"]["t"]["flash_assists"], 1)
        self.assertEqual(players["112"]["side_stats"]["t"]["enemies_flashed"], 1)

    def test_missing_event_stream_does_not_invent_side_metrics(self):
        data = side_demo()
        del data["kills"]
        self.assertFalse(parse_player_stats(data)[0].get("side_stats"))

    def test_post_round_scored_death_before_official_end_is_preserved(self):
        data = side_demo()
        data["rounds"][0]["endTick"] = 25
        data["rounds"][0]["endOfficiallyTick"] = 100
        player = parse_player_stats(data)[0]
        self.assertEqual(player["side_stats"]["t"]["kills"], 2)
        self.assertEqual(player["side_stats"]["t"]["flash_assists"], 0)

    def test_round_without_deaths_is_not_excluded_from_kast(self):
        data = side_demo()
        data["kills"] = []
        for player in data["players"].values():
            player.update(killCount=0, deathCount=0, assistCount=0)
        player = parse_player_stats(data)[0]
        self.assertEqual(player["side_stats"]["t"]["kast"], 100)
        self.assertEqual(player["side_stats"]["ct"]["kast"], 100)

    def test_world_disconnect_does_not_add_a_scored_death(self):
        data = side_demo()
        data["kills"].append(
            {
                "roundNumber": 2,
                "tick": 150,
                "killerSteamId": "111",
                "victimSteamId": "111",
                "killerSide": 3,
                "victimSide": 3,
                "weaponName": "World",
            }
        )
        player = parse_player_stats(data)[0]
        self.assertEqual(player["side_stats"]["ct"]["deaths"], 1)

    def test_world_damage_without_a_player_killer_is_a_real_death(self):
        data = side_demo()
        data["players"]["222"]["deathCount"] += 1
        data["kills"].append(
            {
                "roundNumber": 2,
                "tick": 150,
                "killerSteamId": 0,
                "victimSteamId": "222",
                "killerSide": 0,
                "victimSide": 2,
                "weaponName": "World",
            }
        )
        players = {str(p["steam_id"]): p for p in parse_player_stats(data)}
        self.assertEqual(players["222"]["side_stats"]["t"]["deaths"], 1)

    def test_disconnected_player_does_not_gain_survival_or_rounds(self):
        data = side_demo()
        data["players"]["222"]["killCount"] = 0
        data["playerEconomies"] = [
            r
            for r in data["playerEconomies"]
            if not (r["roundNumber"] == 2 and r["steamId"] == "222")
        ]
        data["kills"] = [
            k for k in data["kills"] if not (k["roundNumber"] == 2 and k["killerSteamId"] == "222")
        ]
        data["damages"] = [
            d
            for d in data["damages"]
            if not (d["roundNumber"] == 2 and d["attackerSteamId"] == "222")
        ]
        players = {str(p["steam_id"]): p for p in parse_player_stats(data)}
        self.assertNotIn("t", players["222"]["side_stats"])

    def test_partial_damage_stream_is_not_displayed_as_zero(self):
        data = side_demo()
        data["damages"] = []
        player = parse_player_stats(data)[0]
        self.assertIsNone(player["side_stats"]["t"]["adr"])
        self.assertIsNone(player["side_stats"]["ct"]["rws"])


class DemoSidePersistenceTests(StatsDatabaseCase):
    def test_import_saves_detailed_sides_and_page_reads_them(self):
        player = parse_player_stats(side_demo())[0]
        insert_match_stat(
            self.conn, self.match_id, self.player_id, self.team1, "t1", player, "Mirage"
        )
        row = dict(self.conn.execute("SELECT * FROM match_stats").fetchone())
        saved = json.loads(row["side_stats_json"])
        self.assertEqual(saved["t"]["clutches_won"], 1)
        view = _build_match_player_row(row, "t1", "A", "Alpha")
        self.assertEqual(view["side_views"]["t"]["kast"], 100)
        self.assertEqual(view["side_views"]["ct"]["assists"], 1)

    def test_all_maps_weight_side_percentages_by_side_rounds(self):
        player = parse_player_stats(side_demo())[0]
        rows = []
        for rounds, kast, kills in ((1, 100, 1), (3, 0, 2)):
            values = {**player["side_stats"]["t"], "rounds": rounds, "kast": kast, "kills": kills}
            rows.append(
                {
                    "player_id": self.player_id,
                    "nickname": "Audit",
                    "avatar": None,
                    "side_stats_json": json.dumps({"t": values}),
                    "rounds_played": rounds,
                }
            )
        row = _aggregate_match_rows(rows, "t1", "A", "Alpha")[0]
        self.assertEqual(row["side_views"]["t"]["kast"], 25)
        self.assertEqual(row["side_views"]["t"]["kills"], 3)
        self.assertEqual(row["side_views"]["t"]["maps"], 2)


class DemoSideBackfillTests(StatsDatabaseCase):
    def prepare(self):
        data = side_demo()
        data["mapName"] = "de_mirage"
        demo_dir = Path(self.temp_dir.name)
        (demo_dir / "audit.dem").write_bytes(b"demo-fixture")
        self.conn.execute(
            "UPDATE matches SET demo_file=? WHERE id=?", (json.dumps(["audit.dem"]), self.match_id)
        )
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Mirage",
            kills=2,
            deaths=1,
            assists=1,
            rating=9.99,
        )
        self.conn.commit()
        with patch("services.demo_side_backfill.run_analysis", return_value=data):
            return prepare_side_backfill(self.conn, demo_dir, demo_dir / "analysis")

    def test_backfill_preserves_formal_results_and_is_idempotent(self):
        plan = self.prepare()
        before_match = tuple(self.conn.execute("SELECT * FROM matches").fetchone())
        self.assertEqual(apply_side_backfill(self.conn, plan), 1)
        self.assertEqual(apply_side_backfill(self.conn, plan), 1)
        row = self.conn.execute("SELECT * FROM match_stats").fetchone()
        self.assertEqual(row["rating"], 9.99)
        self.assertEqual(row["kills"], 2)
        self.assertEqual(row["assists"], 1)
        self.assertTrue(row["side_stats_json"])
        self.assertEqual(tuple(self.conn.execute("SELECT * FROM matches").fetchone()), before_match)

    def test_conflicting_or_superseded_record_is_not_overwritten(self):
        plan = self.prepare()
        self.conn.execute("UPDATE match_stats SET data_status='superseded'")
        self.conn.commit()
        with self.assertRaises(ValueError):
            apply_side_backfill(self.conn, plan)
        self.assertIsNone(
            self.conn.execute("SELECT side_stats_json FROM match_stats").fetchone()[0]
        )

    def test_historical_demo_identity_survives_account_data_transfer(self):
        self.prepare()
        self.conn.execute("UPDATE players SET steam_id='999' WHERE id=?", (self.player_id,))
        self.conn.execute(
            "INSERT INTO match_kill_events(match_id,map_name,killer_player_id,killer_steam_id) VALUES(?,?,?,?)",
            (self.match_id, "de_mirage", self.player_id, "111"),
        )
        data = side_demo()
        data["mapName"] = "Mirage"
        with patch("services.demo_side_backfill.run_analysis", return_value=data):
            plan = prepare_side_backfill(
                self.conn, Path(self.temp_dir.name), Path(self.temp_dir.name) / "analysis"
            )
        self.assertEqual(len(plan["updates"]), 1)
        self.assertEqual(plan["updates"][0]["before"]["player_id"], self.player_id)

    def test_transaction_rolls_back_earlier_updates_on_late_conflict(self):
        plan = self.prepare()
        add_stat(
            self.conn,
            self.match_id,
            self.player_id,
            self.team1,
            "Nuke",
            kills=2,
            deaths=1,
            assists=1,
        )
        second_id = self.conn.execute("SELECT MAX(id) FROM match_stats").fetchone()[0]
        self.conn.commit()
        plan["updates"].append({**plan["updates"][0], "id": second_id})
        with self.assertRaises(ValueError):
            apply_side_backfill(self.conn, plan)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM match_stats WHERE side_stats_json IS NOT NULL"
            ).fetchone()[0],
            0,
        )
