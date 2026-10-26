import os
import tempfile
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from app import app
from config import Config
from models import get_db, init_tables
from services.performance_service import refresh_player_performance


class StatsForms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.tabs = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "div" and "tab-content" in classes:
            self.tabs.append(attrs)
        if tag == "form" and "match-stats-form" in classes:
            self.current = {"attrs": attrs, "fields": {}}
            self.forms.append(self.current)
        if tag == "input" and self.current is not None and attrs.get("name"):
            self.current["fields"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None

    def for_map(self, name):
        return next(form for form in self.forms if form["fields"].get("map_name") == name)


class DotStatsRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dot-stats-")
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = os.path.join(self.temp.name, "test.db")
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        conn = get_db()
        self.event_id = conn.execute(
            "INSERT INTO events(name) VALUES('Stats recovery cup')"
        ).lastrowid
        self.teams = []
        self.players = []
        for number in (1, 2):
            team_id = conn.execute(
                "INSERT INTO teams(name,short_name) VALUES(?,?)",
                (f"Stats team {number}", f"S{number}"),
            ).lastrowid
            self.teams.append(team_id)
            self.players.append(
                conn.execute(
                    "INSERT INTO players(nickname,team_id) VALUES(?,?)",
                    (f"Stats player {number}", team_id),
                ).lastrowid
            )
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,status,bo_format,match_time,
               map1,map2,map1_t1,map1_t2,map2_t1,map2_t2,team1_score,team2_score)
               VALUES(?,?,?,'upcoming','BO3','2027-01-01T12:00',
               'de_mirage','de_nuke',13,8,0,0,0,0)""",
            (self.event_id, *self.teams),
        ).lastrowid
        for name in ("de_mirage", "de_nuke"):
            for side, (player_id, team_id) in enumerate(zip(self.players, self.teams), 1):
                conn.execute(
                    """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,map_name,
                       kills,deaths,assists,adr,kast,headshot_percentage,impact,rating,rounds_played,
                       data_source,data_status,data_version)
                       VALUES(?,?,?,?,?,10,8,3,70.5,75,50,1.1,1.2,21,'manual_review','final',1)""",
                    (self.match_id, player_id, team_id, f"t{side}", name),
                )
        refresh_player_performance(conn, self.players)
        conn.commit()
        conn.close()
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["admin_id"] = 1
            session["admin_username"] = "suite-test-admin"
            session["csrf_token"] = "stats-recovery-test"

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_cookie)
        self.temp.cleanup()

    def payload(self):
        values = {"csrf_token": "stats-recovery-test", "map_name": "de_nuke"}
        for player_id, team_id in zip(self.players, self.teams):
            for key, value in {
                "kills": "21",
                "deaths": "17",
                "assists": "6",
                "adr": "92.4",
                "kast": "83.3",
                "hs": "61.5",
                "impact": "1.37",
                "rating": "999",
                "team_id": str(team_id),
            }.items():
                values[f"{key}_{player_id}"] = value
        return values

    def state(self):
        conn = get_db()
        try:
            return {
                "stats": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM match_stats WHERE match_id=? ORDER BY id", (self.match_id,)
                    )
                ],
                "summary": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM player_performance_summary ORDER BY player_id"
                    )
                ],
            }
        finally:
            conn.close()

    def assert_refilled(self, response):
        page = (
            self.client.get(response.headers["Location"])
            if response.status_code == 302
            else response
        )
        parsed = StatsForms(page.get_data(as_text=True))
        selected = parsed.for_map("de_nuke")
        other = parsed.for_map("de_mirage")
        for player_id in self.players:
            for field in ("kills", "deaths", "assists", "adr", "kast", "hs", "impact"):
                self.assertEqual(
                    selected["fields"][f"{field}_{player_id}"],
                    self.payload()[f"{field}_{player_id}"],
                )
            self.assertEqual(selected["fields"][f"rating_{player_id}"], "1.2")
            self.assertEqual(other["fields"][f"kills_{player_id}"], "10")
        self.assertEqual(response.status_code, 400)
        self.assertIn("data-server-rejected", selected["attrs"])
        self.assertNotIn("data-server-rejected", other["attrs"])
        self.assertEqual(
            [tab["id"] for tab in parsed.tabs if "active" in tab["class"].split()], ["tab-1"]
        )

    def test_unconfirmed_map_score_retains_values_and_selected_map_without_a_browser_draft(self):
        before = self.state()
        response = self.client.post(f"/admin/matches/{self.match_id}/stats", data=self.payload())
        self.assert_refilled(response)
        self.assertIn("该地图比分尚未确认", response.get_data(as_text=True))
        self.assertEqual(self.state(), before)

        conn = get_db()
        conn.execute("UPDATE matches SET map2_t1=13,map2_t2=8 WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        saved = self.client.post(f"/admin/matches/{self.match_id}/stats", data=self.payload())
        self.assertEqual(saved.status_code, 302)
        rows = [row for row in self.state()["stats"] if row["map_name"] == "de_nuke"]
        current = [row for row in rows if row["data_status"] == "final"]
        self.assertEqual(len(current), 2)
        self.assertEqual(len([row for row in rows if row["data_status"] == "superseded"]), 2)
        for row in current:
            self.assertEqual((row["kills"], row["deaths"], row["assists"]), (21, 17, 6))
            self.assertEqual(
                (row["adr"], row["kast"], row["headshot_percentage"]), (92.4, 83.3, 61.5)
            )
            self.assertEqual((row["data_version"], row["rounds_played"]), (2, 21))
            self.assertNotEqual(row["rating"], 999)

    def test_transaction_error_rolls_back_every_row_and_keeps_both_sides_in_the_form(self):
        conn = get_db()
        conn.execute("UPDATE matches SET map2_t1=13,map2_t2=8 WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        before = self.state()
        with patch(
            "blueprints.admin_matches.refresh_player_performance",
            side_effect=RuntimeError("test failure"),
        ):
            response = self.client.post(
                f"/admin/matches/{self.match_id}/stats", data=self.payload()
            )
        self.assert_refilled(response)
        self.assertEqual(self.state(), before)

    def test_completed_match_remains_read_only(self):
        conn = get_db()
        conn.execute("UPDATE matches SET status='completed' WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        before = self.state()
        response = self.client.post(f"/admin/matches/{self.match_id}/stats", data=self.payload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
