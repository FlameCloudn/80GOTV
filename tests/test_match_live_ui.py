import os
import tempfile
import unittest
from pathlib import Path

from app import app
from config import Config
from models import get_db, init_tables


class MatchLiveUiTests(unittest.TestCase):
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
               VALUES('Live UI Test', 'LIVE', '2026-07-01', '2026-08-01', 'ongoing')"""
        ).lastrowid
        team1_id = conn.execute(
            "INSERT INTO teams(name, short_name, logo) VALUES('Team One', 'T1', 'team-one.png')"
        ).lastrowid
        team2_id = conn.execute(
            "INSERT INTO teams(name, short_name) VALUES('Team Two', 'T2')"
        ).lastrowid
        self.match_id = conn.execute(
            """INSERT INTO matches(event_id, team1_id, team2_id, match_time, status)
               VALUES(?, ?, ?, '2026-07-20T20:00', 'live')""",
            (event_id, team1_id, team2_id),
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

    def test_live_page_keeps_rows_stable_between_polls(self):
        response = self.client.get(f"/matches/{self.match_id}/live")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn('id="liveApp" data-i18n-ignore', html)
        self.assertIn("ensurePlayerRows", html)
        self.assertIn("container.replaceChildren(fragment)", html)
        self.assertNotIn("setInterval(fetchLive", html)
        self.assertNotIn("el.innerHTML = html", html)

    def test_live_page_uses_team_logo_and_complete_weapon_manifest(self):
        response = self.client.get(f"/matches/{self.match_id}/live")
        html = response.get_data(as_text=True)

        self.assertIn("/static/uploads/team-one.png", html)
        self.assertIn('class="logo-fallback"', html)
        self.assertIn("WEAPON_ICON_FILES", html)

        project_root = Path(__file__).resolve().parents[1]
        required_icons = (
            "aug.svg",
            "molotov.svg",
            "smokegrenade.svg",
            "ump45.svg",
            "xm1014.svg",
        )
        for filename in required_icons:
            self.assertTrue(
                (project_root / "resources" / "icons" / "match" / filename).is_file(),
                filename,
            )

    def test_match_detail_embeds_fixed_24_round_live_board(self):
        response = self.client.get(f"/matches/{self.match_id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn("比赛数据直播", html)
        self.assertIn('id="roundTeam1"', html)
        self.assertIn('id="roundTeam2"', html)
        self.assertIn('class="round-divider"', html)
        self.assertIn("grid-template-columns:repeat(24,minmax(0,1fr))", html)
        self.assertIn("roundIndex<24", html)
        self.assertIn("roundNumber<24", html)
        self.assertIn("width:min(100%,20px)", html)
        self.assertIn("width:18px;height:18px", html)
        self.assertIn("const sides=currentTeamSides(team1,team2)", html)
        self.assertIn("applyTeamSide(1,sides[0])", html)
        self.assertIn("applyTeamSide(2,sides[1])", html)
        self.assertIn("renderTeam('team1Players',data.players_t1)", html)
        self.assertIn("renderTeam('team2Players',data.players_t2)", html)
        self.assertNotIn("const team1IsCt=", html)


if __name__ == "__main__":
    unittest.main()
