import json
import os
import re
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables
from tests.test_dot_stats_recovery import StatsForms


class AdminStatsRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = Config.DATABASE
        self.original_testing = app.config["TESTING"]
        self.original_secure = app.config["SESSION_COOKIE_SECURE"]
        Config.DATABASE = os.path.join(self.temp.name, "stats.db")
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        conn = get_db()
        self.event_id = conn.execute(
            "INSERT INTO events(name,slug,status) VALUES('Revision Cup','revision-cup','ongoing')"
        ).lastrowid
        self.teams = [
            conn.execute("INSERT INTO teams(name) VALUES(?)", (name,)).lastrowid
            for name in ("Alpha", "Beta")
        ]
        self.players = [
            conn.execute(
                "INSERT INTO players(nickname,team_id) VALUES(?,?)", (name, team_id)
            ).lastrowid
            for name, team_id in zip(("EditorOne", "EditorTwo"), self.teams)
        ]
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,team1_players,team2_players,
                status,bo_format,team1_score,team2_score,map1,map1_t1,map1_t2)
                VALUES(?,?,?,?,?,'live','BO1',0,0,'de_dust2',13,10)""",
            (self.event_id, *self.teams, *[json.dumps([pid]) for pid in self.players]),
        ).lastrowid
        for player_id, team_id, side, kills in zip(self.players, self.teams, ("t1", "t2"), (19, 10)):
            conn.execute(
                """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,map_name,
                    kills,deaths,assists,adr,kast,headshot_percentage,impact,rating,
                    rounds_played,data_version,data_status,first_kills,side_stats_json)
                    VALUES(?,?,?,?,'Dust2',?,10,3,80,75,50,1.1,1.2,23,2,'final',2,?)""",
                (self.match_id, player_id, team_id, side, kills, '{"t":{"kills":9}}'),
            )
        conn.commit()
        conn.close()
        self.client = self.browser()

    def tearDown(self):
        Config.DATABASE = self.original_db
        app.config.update(TESTING=self.original_testing, SESSION_COOKIE_SECURE=self.original_secure)
        self.temp.cleanup()

    def browser(self):
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(admin_id=1, admin_username="revision-admin", csrf_token="revision-test")
        return client

    @property
    def url(self):
        return f"/admin/matches/{self.match_id}/stats"

    def form(self, client=None, index=0):
        response = (client or self.client).get(self.url)
        self.assertEqual(response.status_code, 200)
        return StatsForms(response.get_data(as_text=True)).forms[index]["fields"]

    def rows(self):
        conn = get_db()
        rows = [dict(row) for row in conn.execute("SELECT * FROM match_stats ORDER BY id")]
        conn.close()
        return rows

    def post(self, form, client=None):
        return (client or self.client).post(self.url, data=form)

    def test_editor_reads_legacy_map_alias_instead_of_empty_defaults(self):
        form = self.form()
        self.assertEqual(form[f"kills_{self.players[0]}"], "19")
        self.assertEqual(form[f"assists_{self.players[0]}"], "3")

    def test_saving_alias_replaces_the_old_version_without_double_counting(self):
        form = self.form()
        form[f"kills_{self.players[0]}"] = "20"
        response = self.post(form)
        self.assertEqual(response.status_code, 302)
        rows = self.rows()
        active = [row for row in rows if row["data_status"] != "superseded"]
        self.assertEqual(len(active), 2)
        self.assertEqual(sum(row["kills"] for row in active if row["player_id"] == self.players[0]), 20)
        self.assertEqual({row["map_name"] for row in active}, {"de_dust2"})
        self.assertEqual({row["data_version"] for row in active}, {3})
        self.assertEqual({row["data_status"] for row in rows[:2]}, {"superseded"})
        self.assertEqual(active[0]["first_kills"], 2)
        self.assertEqual(active[0]["side_stats_json"], '{"t":{"kills":9}}')

    def test_stale_admin_form_cannot_overwrite_another_admin(self):
        other = self.browser()
        form_a, form_b = self.form(), self.form(other)
        form_a[f"kills_{self.players[0]}"] = "20"
        self.assertEqual(self.post(form_a).status_code, 302)
        before = self.rows()
        form_b[f"deaths_{self.players[1]}"] = "11"
        rejected = self.post(form_b, other)
        self.assertEqual(rejected.status_code, 409)
        self.assertIn("请刷新", rejected.get_data(as_text=True))
        self.assertEqual(self.rows(), before)
        returned = StatsForms(rejected.get_data(as_text=True)).forms[0]["fields"]
        self.assertEqual(returned[f"deaths_{self.players[1]}"], "11")
        self.assertEqual(self.post(returned, other).status_code, 409)
        self.assertEqual(self.rows(), before)

    def test_missing_revision_is_rejected_without_writes(self):
        form = self.form()
        form.pop("stats_revision", None)
        form[f"kills_{self.players[0]}"] = "21"
        before = self.rows()
        self.assertEqual(self.post(form).status_code, 409)
        self.assertEqual(self.rows(), before)

    def test_score_change_after_opening_requires_refresh(self):
        form = self.form()
        conn = get_db()
        conn.execute("UPDATE matches SET map1_t2=11 WHERE id=?", (self.match_id,))
        conn.commit()
        conn.close()
        before = self.rows()
        self.assertEqual(self.post(form).status_code, 409)
        self.assertEqual(self.rows(), before)

    def test_in_place_demo_side_update_invalidates_the_form(self):
        form = self.form()
        conn = get_db()
        conn.execute("UPDATE match_stats SET side_stats_json='{}' WHERE match_id=?", (self.match_id,))
        conn.commit()
        conn.close()
        before = self.rows()
        self.assertEqual(self.post(form).status_code, 409)
        self.assertEqual(self.rows(), before)

    def test_unedited_submit_does_not_create_a_revision(self):
        form = self.form()
        before = self.rows()
        self.assertEqual(self.post(form).status_code, 302)
        self.assertEqual(self.rows(), before)

    def test_blank_fields_and_unedited_demo_fields_survive_revision(self):
        form = self.form()
        form[f"assists_{self.players[0]}"] = ""
        self.assertEqual(self.post(form).status_code, 302)
        active = [row for row in self.rows() if row["data_status"] == "final"]
        self.assertEqual(len(active), 2)
        row = next(row for row in active if row["player_id"] == self.players[0])
        self.assertIsNone(row["assists"])
        self.assertEqual(row["first_kills"], 2)
        self.assertEqual(row["side_stats_json"], '{"t":{"kills":9}}')

    def test_second_map_can_save_with_its_own_unchanged_revision(self):
        conn = get_db()
        conn.execute(
            "UPDATE matches SET bo_format='BO3',map2='de_nuke',map2_t1=13,map2_t2=7 WHERE id=?",
            (self.match_id,),
        )
        conn.commit()
        conn.close()
        forms = [tab["fields"] for tab in StatsForms(self.client.get(self.url).text).forms]
        forms[0][f"kills_{self.players[0]}"] = "20"
        self.assertEqual(self.post(forms[0]).status_code, 302)
        forms[1][f"kills_{self.players[0]}"] = "15"
        self.assertEqual(self.post(forms[1]).status_code, 302)

    def test_alias_conflicts_are_not_silently_merged_or_overwritten(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO match_stats(match_id,player_id,map_name,kills,data_status)
                VALUES(?,?,'de_dust2',99,'final')""", (self.match_id, self.players[0]),
        )
        conn.commit()
        conn.close()
        form = self.form()
        before = self.rows()
        response = self.post(form)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows(), before)

    def test_bracket_existing_matches_uses_temporary_player_names(self):
        conn = get_db()
        conn.execute(
            "UPDATE matches SET team1_id=NULL,team2_id=NULL WHERE id=?", (self.match_id,)
        )
        conn.commit()
        conn.close()
        response = self.client.get(f"/admin/events/{self.event_id}/bracket")
        self.assertEqual(response.status_code, 200)
        payload = re.search(r"window\._eventMatches = (.*);", response.get_data(as_text=True))
        matches = json.loads(payload.group(1))
        self.assertEqual(matches[0]["t1_name"], "EditorOne")
        self.assertEqual(matches[0]["t2_name"], "EditorTwo")


if __name__ == "__main__":
    unittest.main()
