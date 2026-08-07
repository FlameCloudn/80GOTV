import json
import os
import tempfile
import unittest

from app import app
from config import Config
from models import get_db, init_tables


class MatchRosterPopupTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

        conn = get_db()
        event_id = conn.execute(
            """INSERT INTO events(name, short_name, start_date, end_date, status)
               VALUES('Roster Event','RE','2026-08-01','2026-08-31','ongoing')"""
        ).lastrowid
        team1_id = conn.execute(
            "INSERT INTO teams(name, short_name, logo) VALUES('Team Alpha','TA','alpha.png')"
        ).lastrowid
        team2_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Team Beta','TB')"
        ).lastrowid
        players1 = [
            conn.execute(
                "INSERT INTO players(nickname, team_id) VALUES(?,?)", (f"A{i}", team1_id)
            ).lastrowid
            for i in range(1, 6)
        ]
        players2 = [
            conn.execute(
                "INSERT INTO players(nickname, team_id) VALUES(?,?)", (f"B{i}", team2_id)
            ).lastrowid
            for i in range(1, 6)
        ]
        user_id = conn.execute(
            "INSERT INTO users(username, password_hash, steam_id64) VALUES('subuser','x','999')"
        ).lastrowid
        sub_player_id = conn.execute(
            "INSERT INTO players(nickname, steam_id) VALUES('SubOne','888')"
        ).lastrowid
        conn.execute(
            """INSERT INTO event_individual_registrations
               (event_id, user_id, player_name, steam_id, assignment_status)
               VALUES(?,?,?,?, 'reserve')""",
            (event_id, user_id, "SubOne", "888"),
        )
        standby_user_id = conn.execute(
            "INSERT INTO users(username, password_hash, steam_id64) VALUES('standby','x','777')"
        ).lastrowid
        conn.execute("INSERT INTO players(nickname, steam_id) VALUES('Standby','666')")
        conn.execute(
            """INSERT INTO event_individual_registrations
               (event_id, user_id, player_name, steam_id, assignment_status)
               VALUES(?,?,?,?, 'reserve')""",
            (event_id, standby_user_id, "Standby", "666"),
        )
        roster1 = players1[:4] + [sub_player_id]
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, team1_players, team2_players,
                                   match_time, status)
               VALUES(?,?,?,?,?,?,?)""",
            (
                event_id,
                team1_id,
                team2_id,
                json.dumps(roster1),
                json.dumps(players2),
                "2026-08-07T13:00",
                "upcoming",
            ),
        ).lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_match_detail_team_logo_popup_lists_players_and_substitutes(self):
        response = self.client.get(f"/matches/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn("match-team-players-popup", html)
        self.assertIn("（替补）", html)
        self.assertIn("SubOne", html)
        self.assertNotIn("Standby", html)
        for name in ("A1", "A2", "A3", "A4", "B1", "B5"):
            self.assertIn(name, html)

    def test_match_detail_popup_links_to_player_pages(self):
        response = self.client.get(f"/matches/{self.match_id}")
        html = response.get_data(as_text=True)
        self.assertIn('class="match-player-link" href="/players/', html)
