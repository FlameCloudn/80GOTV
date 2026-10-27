import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import app
from blueprints.admin_matches import _started_bp_setup_change
from config import Config
from models import CURRENT_SCHEMA_VERSION, get_db, init_tables
from routes.auth import _safe_next_target
from services.bracket_service import build_event_bracket, refresh_event_bracket
from utils.bp_manager import init_bp_state
from utils.helpers import (
    ensure_unique_match_slug,
    record_match_slug_alias,
    resolve_match_ref,
    resolve_match_slug,
)


def _bracket_nodes(data):
    return {
        match["id"]: match
        for section in data["tournament"]["sections"]
        for round_data in section["rounds"]
        for match in round_data["matches"]
    }


class AdminLinksSecurityFollowupTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()

        conn = get_db()
        self.event_id = conn.execute(
            """INSERT INTO events(name,short_name,slug,status)
               VALUES('后续测试赛事','FT','followup-cup','upcoming')"""
        ).lastrowid
        self.team_ids = [
            conn.execute(
                "INSERT INTO teams(name,short_name) VALUES(?,?)",
                (f"后续队伍 {index}", f"F{index}"),
            ).lastrowid
            for index in range(1, 5)
        ]
        self.match_id = conn.execute(
            """INSERT INTO matches(
                   event_id,team1_id,team2_id,team1_score,team2_score,match_time,
                   bo_format,stage,status,map1,map_pool,slug
               ) VALUES(?,?,?,1,0,'2026-10-27T20:00','BO3','半决赛','upcoming',
                        'de_mirage','[\"Nuke\",\"Mirage\",\"Ancient\"]','followup-current')""",
            (self.event_id, self.team_ids[0], self.team_ids[1]),
        ).lastrowid
        self.admin_id = conn.execute(
            "INSERT INTO admins(username,password_hash) VALUES(?,?)",
            ("followup-test-admin", generate_password_hash("local-test-password")),
        ).lastrowid
        conn.commit()
        conn.close()

        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_id"] = self.admin_id
            browser_session["admin_username"] = "followup-test-admin"
            browser_session["csrf_token"] = "followup-csrf"

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

    def _admin_post(self, **overrides):
        payload = {
            "csrf_token": "followup-csrf",
            "event_id": str(self.event_id),
            "match_time": "2026-10-27T20:00",
            "bo_format": "BO3",
            "stage": "半决赛",
            "status": "upcoming",
            "map1": "de_mirage",
            "stream_url": "",
        }
        payload.update(overrides)
        return self.client.post(f"/admin/matches/edit/{self.match_id}", data=payload)

    def test_bp_started_match_rejects_setup_edit_without_saving_any_fields(self):
        conn = get_db()
        state = init_bp_state("BO3")
        conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False), self.match_id),
        )
        conn.commit()
        before = conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone()
        before = dict(before)
        conn.close()

        response = self._admin_post(
            bo_format="BO1",
            map1="de_dust2",
            status="live",
            stream_url="https://live.example.invalid/room",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("BP", response.get_data(as_text=True))
        conn = get_db()
        after = dict(conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone())
        conn.close()
        for field in (
            "event_id",
            "team1_id",
            "team2_id",
            "team1_score",
            "team2_score",
            "match_time",
            "bo_format",
            "stage",
            "status",
            "map1",
            "map_pool",
            "bp_state",
            "stream_url",
        ):
            self.assertEqual(after[field], before[field], field)

    def test_bp_start_between_precheck_and_write_lock_blocks_stale_admin_save(self):
        conn = get_db()
        before = dict(conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone())
        conn.close()

        precheck_reached = threading.Event()
        allow_route_to_continue = threading.Event()
        response_box = []
        error_box = []
        call_count = 0
        original_check = _started_bp_setup_change

        def pause_after_initial_check(values, existing):
            nonlocal call_count
            result = original_check(values, existing)
            if call_count == 0:
                call_count += 1
                precheck_reached.set()
                if not allow_route_to_continue.wait(timeout=5):
                    raise TimeoutError("等待并发 BP 写入超时")
            return result

        def submit_stale_form():
            try:
                response_box.append(
                    self._admin_post(
                        bo_format="BO1",
                        map1="de_dust2",
                        status="live",
                        stream_url="https://live.example.invalid/room",
                    )
                )
            except Exception as exc:
                error_box.append(exc)

        request_thread = threading.Thread(target=submit_stale_form, daemon=True)
        try:
            with patch(
                "blueprints.admin_matches._started_bp_setup_change",
                side_effect=pause_after_initial_check,
            ):
                request_thread.start()
                try:
                    self.assertTrue(precheck_reached.wait(timeout=5))
                    bp_state = json.dumps(init_bp_state("BO3"), ensure_ascii=False)
                    writer = get_db()
                    writer.execute(
                        "UPDATE matches SET bp_state=? WHERE id=?", (bp_state, self.match_id)
                    )
                    writer.commit()
                    writer.close()
                finally:
                    allow_route_to_continue.set()
                request_thread.join(timeout=10)
        finally:
            allow_route_to_continue.set()
            if request_thread.ident:
                request_thread.join(timeout=10)

        self.assertFalse(request_thread.is_alive(), "后台保存请求没有结束")
        if error_box:
            raise error_box[0]
        self.assertEqual(len(response_box), 1)
        self.assertEqual(response_box[0].status_code, 400)
        conflict_html = response_box[0].get_data(as_text=True)
        self.assertIn("赛制 (已锁定)", conflict_html)
        self.assertIn('value="BO3"', conflict_html)

        conn = get_db()
        after = dict(conn.execute("SELECT * FROM matches WHERE id=?", (self.match_id,)).fetchone())
        conn.close()
        for field in (
            "event_id",
            "team1_id",
            "team2_id",
            "team1_score",
            "team2_score",
            "match_time",
            "bo_format",
            "stage",
            "status",
            "map1",
            "map_pool",
            "stream_url",
        ):
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(after["bp_state"], bp_state)

    def test_bp_started_match_form_displays_locked_setup(self):
        conn = get_db()
        conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?",
            (json.dumps(init_bp_state("BO3"), ensure_ascii=False), self.match_id),
        )
        conn.commit()
        conn.close()

        response = self.client.get(f"/admin/matches/edit/{self.match_id}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("赛制 (已锁定)", html)
        self.assertNotIn('<select name="bo_format"', html)

    def test_bracket_refuses_bo_change_after_bp_started(self):
        conn = get_db()
        payload = {
            "tournament": {
                "format_key": "4se",
                "bo_format": "BO3",
                "teams": [
                    {"id": f"t{index}", "db_id": team_id, "name": f"后续队伍 {index}"}
                    for index, team_id in enumerate(self.team_ids, 1)
                ],
                "sections": [
                    {
                        "label": "淘汰赛",
                        "rounds": [
                            {
                                "name": "半决赛",
                                "matches": [
                                    {"id": "SF_M1", "team1": "t1", "team2": "t4"},
                                    {"id": "SF_M2", "team1": "t2", "team2": "t3"},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        data = build_event_bracket(conn, self.event_id, payload)
        first_id = _bracket_nodes(data)["SF_M1"]["match_id"]
        conn.execute(
            "UPDATE matches SET bp_state=? WHERE id=?",
            (json.dumps(init_bp_state("BO3"), ensure_ascii=False), first_id),
        )
        conn.commit()
        changed = json.loads(json.dumps(data))
        _bracket_nodes(changed)["SF_M1"]["bo_format"] = "BO1"

        with self.assertRaisesRegex(ValueError, "不能更改比赛赛制"):
            build_event_bracket(conn, self.event_id, changed)
        conn.rollback()
        current = conn.execute(
            "SELECT bo_format,bp_state FROM matches WHERE id=?", (first_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(current["bo_format"], "BO3")
        self.assertTrue(current["bp_state"])

    def test_promoted_match_keeps_old_slug_and_redirects_suffixes_and_query(self):
        conn = get_db()
        payload = {
            "tournament": {
                "format_key": "4se",
                "bo_format": "BO3",
                "teams": [
                    {"id": f"t{index}", "db_id": team_id, "name": f"后续队伍 {index}"}
                    for index, team_id in enumerate(self.team_ids, 1)
                ],
                "sections": [
                    {
                        "label": "淘汰赛",
                        "rounds": [
                            {
                                "name": "半决赛",
                                "matches": [
                                    {"id": "SF_M1", "team1": "t1", "team2": "t4"},
                                    {"id": "SF_M2", "team1": "t2", "team2": "t3"},
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        data = build_event_bracket(conn, self.event_id, payload)
        nodes = _bracket_nodes(data)
        final_id = nodes["F_M1"]["match_id"]
        first_id = nodes["SF_M1"]["match_id"]
        old_slug = conn.execute("SELECT slug FROM matches WHERE id=?", (final_id,)).fetchone()[
            "slug"
        ]
        conn.execute(
            "UPDATE matches SET status='completed',team1_score=2,team2_score=0 WHERE id=?",
            (first_id,),
        )
        refresh_event_bracket(conn, self.event_id)
        conn.commit()
        final = conn.execute("SELECT slug,team1_id FROM matches WHERE id=?", (final_id,)).fetchone()
        alias = conn.execute(
            "SELECT match_id FROM match_slug_aliases WHERE slug=?", (old_slug,)
        ).fetchone()
        conn.close()

        self.assertNotEqual(final["slug"], old_slug)
        self.assertEqual(final["team1_id"], self.team_ids[0])
        self.assertEqual(alias["match_id"], final_id)
        self.assertEqual(resolve_match_slug(old_slug), final_id)
        resolved = resolve_match_ref(old_slug)
        self.assertEqual(resolved["id"], final_id)
        self.assertTrue(resolved["is_alias"])

        query = "tab=maps&source=old%2Fbookmark"
        for suffix in ("", "/stats", "/detailed", "/poster", "/download-demo"):
            with self.subTest(suffix=suffix):
                response = self.client.get(
                    f"/matches/{old_slug}{suffix}?{query}", follow_redirects=False
                )
                self.assertEqual(response.status_code, 301)
                self.assertEqual(
                    response.headers["Location"],
                    f"/matches/{final['slug']}{suffix}?{query}",
                )

    def test_alias_conflicts_do_not_retarget_or_take_another_match_slug(self):
        conn = get_db()
        other_id = conn.execute(
            "INSERT INTO matches(event_id,slug) VALUES(?,?)",
            (self.event_id, "protected-current-slug"),
        ).lastrowid
        self.assertFalse(record_match_slug_alias(conn, "protected-current-slug", self.match_id))
        self.assertTrue(record_match_slug_alias(conn, "preserved-old-slug", self.match_id))
        self.assertFalse(record_match_slug_alias(conn, "preserved-old-slug", other_id))
        self.assertNotEqual(
            ensure_unique_match_slug(conn, other_id, "preserved-old-slug"),
            "preserved-old-slug",
        )
        conn.commit()
        conn.close()

        self.assertEqual(resolve_match_slug("protected-current-slug"), other_id)
        self.assertEqual(resolve_match_slug("preserved-old-slug"), self.match_id)

    def test_next_target_allows_normal_local_path_and_rejects_confusing_forms(self):
        safe = "/matches/final-vs-team?tab=maps"
        with app.test_request_context("/login", query_string={"next": safe}):
            self.assertEqual(_safe_next_target(), safe)

        attacks = (
            "//evil.example/path",
            "///evil.example/path",
            "/\\evil.example/path",
            "/\\\\evil.example/path",
            "/%2f%2fevil.example/path",
            "/%252f%252fevil.example/path",
            "/%5cevil.example/path",
            "/%255cevil.example/path",
            "/%250d%250aheader:value",
            "/%C2%85header:value",
            "/matches/good\r\nLocation: https://evil.example",
        )
        for target in attacks:
            with (
                self.subTest(target=target),
                app.test_request_context("/login", query_string={"next": target}),
            ):
                self.assertEqual(_safe_next_target(), "/")

    def test_real_login_response_keeps_safe_query_and_rejects_external_location(self):
        def login(target):
            self.client.get("/login")
            with self.client.session_transaction() as browser_session:
                csrf_token = browser_session["csrf_token"]
            with patch("routes.auth.rate_limit", return_value=True):
                return self.client.post(
                    "/login",
                    data={
                        "csrf_token": csrf_token,
                        "username": "followup-test-admin",
                        "password": "local-test-password",
                        "next": target,
                    },
                )

        normal = login("/matches/final-vs-team?tab=maps")
        self.assertEqual(normal.status_code, 302)
        self.assertEqual(normal.headers["Location"], "/matches/final-vs-team?tab=maps")

        hostile = login("///evil.example/path")
        self.assertEqual(hostile.status_code, 302)
        self.assertEqual(hostile.headers["Location"], "/")


class ExistingSchemaFollowupMigrationTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        Config.DATABASE = self.database_path

    def tearDown(self):
        Config.DATABASE = self.original_database
        try:
            os.remove(self.database_path)
        except OSError:
            pass

    def test_current_schema_migration_adds_roster_and_champion_snapshot_schema(self):
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE admins(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE teams(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE players(id INTEGER PRIMARY KEY, nickname TEXT);
            CREATE TABLE event_registrations(id INTEGER PRIMARY KEY);
            CREATE TABLE matches(
                id INTEGER PRIMARY KEY, event_id INTEGER, team1_id INTEGER,
                team2_id INTEGER, status TEXT
            );
            CREATE TABLE event_champions(
                id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, team_id INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version,name) VALUES(?,?)",
            (CURRENT_SCHEMA_VERSION, "existing_schema_before_roster_snapshots"),
        )
        conn.execute("INSERT INTO events(id,name) VALUES(1,'迁移测试赛事')")
        conn.execute("INSERT INTO teams(id,name) VALUES(1,'迁移测试队伍')")
        conn.execute("INSERT INTO players(id,nickname) VALUES(1,'迁移测试选手')")
        conn.execute("INSERT INTO event_champions(id,event_id,team_id) VALUES(1,1,1)")
        conn.commit()
        conn.close()

        init_tables()
        conn = get_db()
        first_snapshot_at = conn.execute(
            "SELECT players_snapshot_at FROM event_champions WHERE id=1"
        ).fetchone()[0]
        conn.close()
        init_tables()

        conn = get_db()
        match_columns = {row[1]: row[4] for row in conn.execute("PRAGMA table_info(matches)")}
        champion_columns = {row[1] for row in conn.execute("PRAGMA table_info(event_champions)")}
        self.assertTrue(
            {"roster_snapshot", "team1_registration_id", "team2_registration_id"}.issubset(
                match_columns
            )
        )
        self.assertIsNone(match_columns["roster_snapshot"])
        self.assertIn("players_snapshot_at", champion_columns)
        snapshot_at = conn.execute(
            "SELECT players_snapshot_at FROM event_champions WHERE id=1"
        ).fetchone()[0]
        self.assertIsNotNone(snapshot_at)
        self.assertEqual(snapshot_at, first_snapshot_at)
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM event_champion_players WHERE champion_id=1"
            ).fetchone()[0],
            0,
        )
        self.assertIn(
            "event_champion_players",
            {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            },
        )
        registration_fks = {
            row[3]: row[6] for row in conn.execute("PRAGMA foreign_key_list(matches)").fetchall()
        }
        self.assertEqual(registration_fks["team1_registration_id"], "SET NULL")
        self.assertEqual(registration_fks["team2_registration_id"], "SET NULL")
        champion_fks = {
            (row[2], row[6])
            for row in conn.execute("PRAGMA foreign_key_list(event_champion_players)").fetchall()
        }
        self.assertIn(("event_champions", "CASCADE"), champion_fks)
        self.assertIn(("players", "CASCADE"), champion_fks)
        conn.close()


if __name__ == "__main__":
    unittest.main()
