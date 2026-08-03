import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables


class EventRegistrationManagementTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        self.upload_root = tempfile.mkdtemp()
        self.base_dir_patch = patch("routes.events.BASE_DIR", self.upload_root)
        self.base_dir_patch.start()
        self.individual_open_patch = patch(
            "routes.events._individual_registration_is_open", return_value=True
        )
        self.individual_open_patch.start()
        self.playtime_refresh_patch = patch(
            "routes.events.refresh_registration_playtimes",
            return_value={"configured": True, "refreshed": 0, "unavailable": 0},
        )
        self.playtime_refresh_patch.start()
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()
        self.client = app.test_client()

        conn = get_db()
        conn.execute(
            """INSERT INTO events(
                   name, slug, registration_open, status, start_date, end_date
               ) VALUES(
                   'Registration Test', 'registration-test', 1, 'upcoming',
                   '2026-07-24', '2026-07-31'
               )"""
        )
        self.event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.captain_id = self._insert_user(conn, "Captain", "76561198000000101")
        self.member_id = self._insert_user(conn, "Member", "76561198000000102")
        self.outsider_id = self._insert_user(conn, "Outsider", "76561198000000103")
        conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES(?,?)",
            ("front-admin", generate_password_hash("admin-password")),
        )
        self.admin_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

    def tearDown(self):
        self.playtime_refresh_patch.stop()
        self.individual_open_patch.stop()
        self.base_dir_patch.stop()
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        try:
            os.remove(self.database_path)
        except OSError:
            pass
        shutil.rmtree(self.upload_root, ignore_errors=True)

    @staticmethod
    def _insert_user(conn, username, steam_id):
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, steam_id64, approval_status,
                   group_username, is_bashizhong_student
               ) VALUES(?,?,?,'approved',?,1)""",
            (username, generate_password_hash("password123"), steam_id, username),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _login_user(self, user_id, username):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["user_id"] = user_id
            browser_session["user_username"] = username
            browser_session["csrf_token"] = "registration-csrf"

    def _login_admin(self):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["admin_id"] = self.admin_id
            browser_session["admin_username"] = "front-admin"
            browser_session["csrf_token"] = "registration-csrf"

    def _create_registration(self, include_member=True):
        conn = get_db()
        conn.execute(
            """INSERT INTO event_registrations(
                   event_id, team_name, creator_user_id, status
               ) VALUES(?,?,?,'pending')""",
            (self.event_id, "Test Team", self.captain_id),
        )
        registration_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for slot_index in range(5):
            if slot_index == 0:
                values = (self.captain_id, "Captain", "76561198000000101", 1)
            elif slot_index == 1 and include_member:
                values = (self.member_id, "Member", "76561198000000102", 0)
            else:
                values = (None, f"位置{slot_index + 1}", "", 0)
            conn.execute(
                """INSERT INTO event_registration_slots(
                       registration_id, slot_index, user_id, player_name, steam_id,
                       filled_by_creator
                   ) VALUES(?,?,?,?,?,?)""",
                (registration_id, slot_index, *values),
            )
        conn.commit()
        conn.close()
        return registration_id

    def _create_individual_registrations(self, count, playtimes=None, prefix="Solo"):
        conn = get_db()
        user_ids = []
        for index in range(count):
            user_id = self._insert_user(
                conn,
                f"{prefix} {index}",
                f"7656119800100{index:04d}",
            )
            minutes = playtimes[index] if playtimes is not None else 1000 + index
            conn.execute(
                """
                INSERT INTO event_individual_registrations(
                    event_id, user_id, player_name, steam_id,
                    cs2_playtime_minutes, playtime_status
                ) VALUES(?,?,?,?,?,'public')
                """,
                (
                    self.event_id,
                    user_id,
                    f"{prefix} {index}",
                    f"7656119800100{index:04d}",
                    minutes,
                ),
            )
            user_ids.append(user_id)
        conn.commit()
        conn.close()
        return user_ids

    def _ajax_post(self, path, data=None):
        payload = {"csrf_token": "registration-csrf"}
        payload.update(data or {})
        return self.client.post(
            path,
            data=payload,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    @staticmethod
    def _logo_upload(color=(28, 104, 166), name="team-logo.png"):
        image_data = io.BytesIO()
        Image.new("RGB", (900, 600), color).save(image_data, format="PNG")
        image_data.seek(0)
        return image_data, name

    def test_registration_creator_is_saved_as_captain(self):
        self._login_user(self.captain_id, "Captain")
        response = self.client.post(
            f"/events/{self.event_id}/register",
            data={
                "csrf_token": "registration-csrf",
                "team_name": "Captain Team",
                "my_slot": "2",
                "team_logo": self._logo_upload(),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        conn = get_db()
        registration = conn.execute(
            "SELECT * FROM event_registrations WHERE event_id=?", (self.event_id,)
        ).fetchone()
        captain_slot = conn.execute(
            """SELECT * FROM event_registration_slots
               WHERE registration_id=? AND user_id=?""",
            (registration["id"], self.captain_id),
        ).fetchone()
        conn.close()
        self.assertEqual(registration["creator_user_id"], self.captain_id)
        self.assertTrue(registration["team_logo"])
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.upload_root,
                    "static",
                    "uploads",
                    "team_logos",
                    registration["team_logo"],
                )
            )
        )
        self.assertEqual(captain_slot["slot_index"], 2)

    def test_join_uses_json_and_returns_updated_registration_without_redirect(self):
        registration_id = self._create_registration(include_member=False)
        self._login_user(self.member_id, "Member")
        response = self._ajax_post(f"/events/{self.event_id}/join/{registration_id}/1")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response.headers)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("Member", payload["html"])

        conn = get_db()
        slot = conn.execute(
            """SELECT user_id FROM event_registration_slots
               WHERE registration_id=? AND slot_index=1""",
            (registration_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(slot["user_id"], self.member_id)

    def test_captain_can_rename_remove_member_and_dissolve(self):
        registration_id = self._create_registration()
        self._login_user(self.captain_id, "Captain")

        renamed = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/rename",
            {"team_name": "Renamed Team"},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertTrue(renamed.get_json()["success"])

        removed = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/slots/1/remove"
        )
        self.assertEqual(removed.status_code, 200)
        conn = get_db()
        slot = conn.execute(
            """SELECT user_id FROM event_registration_slots
               WHERE registration_id=? AND slot_index=1""",
            (registration_id,),
        ).fetchone()
        self.assertIsNone(slot["user_id"])
        conn.close()

        dissolved = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/dissolve"
        )
        self.assertEqual(dissolved.status_code, 200)
        conn = get_db()
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM event_registrations WHERE id=?", (registration_id,)
            ).fetchone()[0],
            0,
        )
        conn.close()

    def test_captain_can_upload_replace_and_remove_team_logo_without_redirect(self):
        registration_id = self._create_registration()
        self._login_user(self.captain_id, "Captain")

        uploaded = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/logo",
            {"team_logo": self._logo_upload()},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertNotIn("Location", uploaded.headers)
        self.assertTrue(uploaded.get_json()["success"])

        conn = get_db()
        first_logo = conn.execute(
            "SELECT team_logo FROM event_registrations WHERE id=?", (registration_id,)
        ).fetchone()["team_logo"]
        conn.close()
        first_path = os.path.join(self.upload_root, "static", "uploads", "team_logos", first_logo)
        self.assertTrue(os.path.isfile(first_path))
        self.assertIn(f"/static/uploads/team_logos/{first_logo}", uploaded.get_json()["html"])
        with Image.open(first_path) as saved_logo:
            self.assertLessEqual(max(saved_logo.size), 512)
            self.assertEqual(saved_logo.format, "PNG")

        replaced = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/logo",
            {"team_logo": self._logo_upload((180, 60, 50), "replacement.jpg")},
        )
        self.assertEqual(replaced.status_code, 200)
        conn = get_db()
        second_logo = conn.execute(
            "SELECT team_logo FROM event_registrations WHERE id=?", (registration_id,)
        ).fetchone()["team_logo"]
        conn.close()
        self.assertNotEqual(first_logo, second_logo)
        self.assertFalse(os.path.exists(first_path))

        removed = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/logo/remove"
        )
        self.assertEqual(removed.status_code, 200)
        conn = get_db()
        stored_logo = conn.execute(
            "SELECT team_logo FROM event_registrations WHERE id=?", (registration_id,)
        ).fetchone()["team_logo"]
        conn.close()
        self.assertIsNone(stored_logo)

    def test_team_logo_upload_rejects_invalid_file_and_non_captain(self):
        registration_id = self._create_registration()
        self._login_user(self.captain_id, "Captain")
        invalid = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/logo",
            {"team_logo": (io.BytesIO(b"not an image"), "fake.png")},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(invalid.get_json()["success"])

        self._login_user(self.outsider_id, "Outsider")
        forbidden = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/logo",
            {"team_logo": self._logo_upload()},
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertFalse(forbidden.get_json()["success"])

    def test_individual_registration_without_avatar_uses_name_initial(self):
        conn = get_db()
        conn.execute(
            """INSERT INTO event_individual_registrations(
                   event_id, user_id, player_name, steam_id, assignment_status
               ) VALUES(?,?,?,?, 'pending')""",
            (
                self.event_id,
                self.member_id,
                "Member",
                "76561198000000102",
            ),
        )
        conn.commit()
        conn.close()

        html = self.client.get("/events/registration-test").get_data(as_text=True)
        self.assertIn(
            '<span class="event-individual-avatar-fallback" aria-hidden="true">M</span>',
            html,
        )

    def test_non_captain_cannot_manage_team(self):
        registration_id = self._create_registration()
        self._login_user(self.outsider_id, "Outsider")
        response = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/rename",
            {"team_name": "Hijacked Team"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.get_json()["success"])

    def test_admin_can_edit_member_and_remove_team_from_front_page(self):
        registration_id = self._create_registration()
        self._login_admin()
        updated = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/slots/1/update",
            {
                "player_name": "Edited Member",
                "steam_id": "76561198000000999",
            },
        )
        self.assertEqual(updated.status_code, 200)
        conn = get_db()
        slot = conn.execute(
            """SELECT player_name, steam_id FROM event_registration_slots
               WHERE registration_id=? AND slot_index=1""",
            (registration_id,),
        ).fetchone()
        self.assertEqual(slot["player_name"], "Edited Member")
        self.assertEqual(slot["steam_id"], "76561198000000999")
        conn.close()

        dissolved = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/dissolve"
        )
        self.assertEqual(dissolved.status_code, 200)

    def test_admin_can_transfer_captain_to_another_registered_member(self):
        registration_id = self._create_registration()
        self._login_admin()

        transferred = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/slots/1/captain"
        )
        self.assertEqual(transferred.status_code, 200)
        self.assertTrue(transferred.get_json()["success"])
        self.assertIn("队长：Member", transferred.get_json()["html"])
        self.assertIn("@Member", transferred.get_json()["html"])
        self.assertIn("任命队长", transferred.get_json()["html"])

        conn = get_db()
        registration = conn.execute(
            "SELECT creator_user_id FROM event_registrations WHERE id=?",
            (registration_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(registration["creator_user_id"], self.member_id)

        self._login_user(self.member_id, "Member")
        renamed = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/rename",
            {"team_name": "Member Leads Now"},
        )
        self.assertEqual(renamed.status_code, 200)

        self._login_user(self.captain_id, "Captain")
        former_captain = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/rename",
            {"team_name": "Old Captain Cannot Rename"},
        )
        self.assertEqual(former_captain.status_code, 403)

    def test_non_admin_cannot_transfer_captain(self):
        registration_id = self._create_registration()
        self._login_user(self.captain_id, "Captain")
        response = self._ajax_post(
            f"/events/{self.event_id}/registrations/{registration_id}/slots/1/captain"
        )
        self.assertEqual(response.status_code, 403)

    def test_individual_registration_and_withdraw_use_ajax(self):
        self._login_user(self.outsider_id, "Outsider")
        registered = self._ajax_post(f"/events/{self.event_id}/register-individual")
        self.assertEqual(registered.status_code, 200)
        self.assertTrue(registered.get_json()["success"])
        self.assertIn("Outsider", registered.get_json()["html"])

        conn = get_db()
        entry = conn.execute(
            """SELECT * FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.outsider_id),
        ).fetchone()
        conn.close()
        self.assertEqual(entry["assignment_status"], "pending")

        withdrawn = self._ajax_post(f"/events/{self.event_id}/individual-registration/withdraw")
        self.assertEqual(withdrawn.status_code, 200)
        self.assertTrue(withdrawn.get_json()["success"])
        conn = get_db()
        count = conn.execute(
            """SELECT COUNT(*) FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.outsider_id),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_individual_registration_launch_date_is_july_20(self):
        from routes.events import _INDIVIDUAL_REGISTRATION_OPENS_AT

        self.assertEqual(
            _INDIVIDUAL_REGISTRATION_OPENS_AT.isoformat(),
            "2026-07-20T00:00:00+08:00",
        )

    def test_individual_registration_is_hidden_and_blocked_before_launch(self):
        self._login_user(self.outsider_id, "Outsider")
        with patch("routes.events._individual_registration_is_open", return_value=False):
            page = self.client.get(f"/events/{self.event_id}")
            self.assertEqual(page.status_code, 301)
            canonical = self.client.get(page.headers["Location"])
            self.assertEqual(canonical.status_code, 200)
            self.assertNotIn("个人报名", canonical.get_data(as_text=True))

            registration = self._ajax_post(f"/events/{self.event_id}/register-individual")
            self.assertEqual(registration.status_code, 403)
            self.assertIn("7 月 20 日", registration.get_json()["error"])

    def test_team_and_individual_registration_are_mutually_exclusive(self):
        registration_id = self._create_registration(include_member=False)
        self._login_user(self.outsider_id, "Outsider")
        individual = self._ajax_post(f"/events/{self.event_id}/register-individual")
        self.assertEqual(individual.status_code, 200)

        join = self._ajax_post(f"/events/{self.event_id}/join/{registration_id}/1")
        self.assertEqual(join.status_code, 409)
        self.assertIn("个人报名", join.get_json()["error"])

        team_create = self.client.post(
            f"/events/{self.event_id}/register",
            data={
                "csrf_token": "registration-csrf",
                "team_name": "Should Not Exist",
                "my_slot": "0",
            },
        )
        self.assertEqual(team_create.status_code, 302)
        conn = get_db()
        self.assertIsNone(
            conn.execute(
                "SELECT id FROM event_registrations WHERE team_name='Should Not Exist'"
            ).fetchone()
        )
        conn.close()

    def _mark_formal_assignment_complete(self):
        registration_id = self._create_registration(include_member=False)
        conn = get_db()
        conn.execute(
            """INSERT INTO event_individual_registrations(
                   event_id, user_id, player_name, steam_id,
                   assignment_status, team_number, assigned_at
               ) VALUES(?,?,?,?, 'assigned', 1, CURRENT_TIMESTAMP)""",
            (
                self.event_id,
                self.captain_id,
                "Captain",
                "76561198000000101",
            ),
        )
        conn.commit()
        conn.close()
        return registration_id

    def test_substitute_registration_waits_for_formal_assignment(self):
        self._login_user(self.outsider_id, "Outsider")
        response = self._ajax_post(f"/events/{self.event_id}/register-substitute")
        self.assertEqual(response.status_code, 409)
        self.assertIn("正式分队完成后", response.get_json()["error"])

    def test_individual_and_substitute_registration_render_as_separate_sections(self):
        self._mark_formal_assignment_complete()
        page = self.client.get(f"/events/{self.event_id}")
        self.assertEqual(page.status_code, 301)
        canonical = self.client.get(page.headers["Location"])
        self.assertEqual(canonical.status_code, 200)
        html = canonical.get_data(as_text=True)
        self.assertIn('data-registration-kind="individual"', html)
        self.assertIn('data-registration-kind="substitute"', html)
        self.assertIn('<h3 class="section-title">个人报名</h3>', html)
        self.assertIn('<h3 class="section-title">替补报名</h3>', html)
        self.assertNotIn("个人报名与替补", html)

    def test_substitute_joins_public_pool_without_using_team_slot(self):
        registration_id = self._mark_formal_assignment_complete()
        self._login_user(self.outsider_id, "Outsider")
        response = self._ajax_post(f"/events/{self.event_id}/register-substitute")
        self.assertEqual(response.status_code, 200)
        self.assertIn("公共替补池", response.get_json()["message"])

        conn = get_db()
        substitute = conn.execute(
            """SELECT assignment_status, team_number, preferred_registration_id
               FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.outsider_id),
        ).fetchone()
        occupied_slots = conn.execute(
            """SELECT COUNT(*) FROM event_registration_slots
               WHERE registration_id=? AND user_id IS NOT NULL""",
            (registration_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(substitute["assignment_status"], "reserve")
        self.assertIsNone(substitute["team_number"])
        self.assertIsNone(substitute["preferred_registration_id"])
        self.assertEqual(occupied_slots, 1)

    def test_substitute_can_choose_and_change_a_specific_team(self):
        registration_id = self._mark_formal_assignment_complete()
        self._login_user(self.outsider_id, "Outsider")

        registered = self._ajax_post(
            f"/events/{self.event_id}/register-substitute",
            {"preferred_registration_id": str(registration_id)},
        )
        self.assertEqual(registered.status_code, 200)
        self.assertIn("Test Team", registered.get_json()["message"])

        changed = self._ajax_post(f"/events/{self.event_id}/register-substitute")
        self.assertEqual(changed.status_code, 200)
        self.assertIn("公共替补", changed.get_json()["message"])

        conn = get_db()
        preferred_id = conn.execute(
            """SELECT preferred_registration_id
               FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.outsider_id),
        ).fetchone()[0]
        conn.close()
        self.assertIsNone(preferred_id)

    def test_substitute_can_withdraw_without_resetting_formal_assignment(self):
        self._mark_formal_assignment_complete()
        self._login_user(self.outsider_id, "Outsider")
        registered = self._ajax_post(f"/events/{self.event_id}/register-substitute")
        self.assertEqual(registered.status_code, 200)
        withdrawn = self._ajax_post(f"/events/{self.event_id}/individual-registration/withdraw")
        self.assertEqual(withdrawn.status_code, 200)
        self.assertIn("取消替补报名", withdrawn.get_json()["message"])

        conn = get_db()
        captain = conn.execute(
            """SELECT assignment_status FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.captain_id),
        ).fetchone()
        outsider = conn.execute(
            """SELECT id FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.outsider_id),
        ).fetchone()
        conn.close()
        self.assertEqual(captain["assignment_status"], "assigned")
        self.assertIsNone(outsider)

    def test_formal_team_member_cannot_register_as_substitute(self):
        self._mark_formal_assignment_complete()
        self._login_user(self.captain_id, "Captain")
        response = self._ajax_post(f"/events/{self.event_id}/register-substitute")
        self.assertEqual(response.status_code, 409)
        self.assertIn("正式队员", response.get_json()["error"])

    def test_admin_balances_full_teams_and_keeps_leftovers_as_reserves(self):
        conn = get_db()
        user_ids = [self.captain_id, self.member_id, self.outsider_id]
        for index in range(9):
            user_ids.append(
                self._insert_user(
                    conn,
                    f"Solo {index}",
                    f"7656119800001{index:04d}",
                )
            )
        users = conn.execute(
            "SELECT id, username, steam_id64 FROM users WHERE id IN ({})".format(
                ",".join("?" for _ in user_ids)
            ),
            user_ids,
        ).fetchall()
        for user in users:
            conn.execute(
                """INSERT INTO event_individual_registrations(
                       event_id, user_id, player_name, steam_id
                   ) VALUES(?,?,?,?)""",
                (self.event_id, user["id"], user["username"], user["steam_id64"]),
            )
        conn.commit()
        conn.close()

        self._login_admin()
        randomized = self._ajax_post(f"/events/{self.event_id}/individual-registration/randomize")
        self.assertEqual(randomized.status_code, 200)
        self.assertTrue(randomized.get_json()["success"])
        self.assertIn("游戏时长平衡", randomized.get_json()["message"])
        self.assertIn("2 支队伍", randomized.get_json()["message"])
        self.assertIn("2 名候补", randomized.get_json()["message"])

        conn = get_db()
        team_sizes = conn.execute(
            """SELECT team_number, COUNT(*) AS player_count
               FROM event_individual_registrations
               WHERE event_id=? AND assignment_status='assigned'
               GROUP BY team_number ORDER BY team_number""",
            (self.event_id,),
        ).fetchall()
        reserve_count = conn.execute(
            """SELECT COUNT(*) FROM event_individual_registrations
               WHERE event_id=? AND assignment_status='reserve'""",
            (self.event_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual([row["player_count"] for row in team_sizes], [5, 5])
        self.assertEqual(reserve_count, 2)

    def test_admin_one_click_fills_partial_team_and_creates_formal_team(self):
        partial_registration_id = self._create_registration(include_member=False)
        applicant_ids = self._create_individual_registrations(
            9,
            playtimes=[2100, 1400, 600, 450, 450, 450, 200, 50, 0],
            prefix="Finalize",
        )

        self._login_admin()
        finalized = self._ajax_post(f"/events/{self.event_id}/individual-registration/finalize")

        self.assertEqual(finalized.status_code, 200)
        payload = finalized.get_json()
        self.assertTrue(payload["success"])
        self.assertIn("补满 1 支现有队伍", payload["message"])
        self.assertIn("新建 1 支正式队伍", payload["message"])

        conn = get_db()
        registrations = conn.execute(
            """
            SELECT id, team_name, creator_user_id
            FROM event_registrations
            WHERE event_id=? AND status='pending'
            ORDER BY id
            """,
            (self.event_id,),
        ).fetchall()
        roster_sizes = conn.execute(
            """
            SELECT r.id, COUNT(s.user_id) AS player_count
            FROM event_registrations r
            JOIN event_registration_slots s ON s.registration_id=r.id
            WHERE r.event_id=? AND r.status='pending'
            GROUP BY r.id ORDER BY r.id
            """,
            (self.event_id,),
        ).fetchall()
        assigned = conn.execute(
            """
            SELECT user_id, assignment_status, team_number
            FROM event_individual_registrations
            WHERE event_id=? ORDER BY id
            """,
            (self.event_id,),
        ).fetchall()
        new_registration = registrations[1]
        new_roster_user_ids = {
            row["user_id"]
            for row in conn.execute(
                """
                SELECT user_id FROM event_registration_slots
                WHERE registration_id=?
                """,
                (new_registration["id"],),
            ).fetchall()
        }
        conn.close()

        self.assertEqual(len(registrations), 2)
        self.assertEqual(registrations[0]["id"], partial_registration_id)
        self.assertEqual(new_registration["team_name"], "个人报名队 1")
        self.assertEqual([row["player_count"] for row in roster_sizes], [5, 5])
        self.assertEqual({row["assignment_status"] for row in assigned}, {"assigned"})
        self.assertEqual({row["user_id"] for row in assigned}, set(applicant_ids))
        self.assertEqual(
            {row["team_number"] for row in assigned},
            {row["id"] for row in registrations},
        )
        self.assertIn(new_registration["creator_user_id"], new_roster_user_ids)

        repeated = self._ajax_post(f"/events/{self.event_id}/individual-registration/finalize")
        self.assertEqual(repeated.status_code, 409)
        conn = get_db()
        registration_count = conn.execute(
            "SELECT COUNT(*) FROM event_registrations WHERE event_id=?",
            (self.event_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(registration_count, 2)

    def test_admin_one_click_creates_full_teams_and_public_substitutes(self):
        self._create_individual_registrations(12, prefix="Twelve")
        self._login_admin()

        finalized = self._ajax_post(f"/events/{self.event_id}/individual-registration/finalize")

        self.assertEqual(finalized.status_code, 200)
        self.assertIn("新建 2 支正式队伍", finalized.get_json()["message"])
        self.assertIn("2 名选手进入公共替补池", finalized.get_json()["message"])
        conn = get_db()
        roster_sizes = conn.execute(
            """
            SELECT COUNT(s.user_id) AS player_count
            FROM event_registrations r
            JOIN event_registration_slots s ON s.registration_id=r.id
            WHERE r.event_id=? GROUP BY r.id ORDER BY r.id
            """,
            (self.event_id,),
        ).fetchall()
        substitute_count = conn.execute(
            """
            SELECT COUNT(*) FROM event_individual_registrations
            WHERE event_id=? AND assignment_status='reserve'
            """,
            (self.event_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual([row["player_count"] for row in roster_sizes], [5, 5])
        self.assertEqual(substitute_count, 2)

    def test_admin_one_click_rejects_unfillable_partial_team_without_writes(self):
        registration_id = self._create_registration(include_member=False)
        self._create_individual_registrations(3, prefix="Too Few")
        self._login_admin()

        finalized = self._ajax_post(f"/events/{self.event_id}/individual-registration/finalize")

        self.assertEqual(finalized.status_code, 409)
        self.assertIn("人数不足", finalized.get_json()["error"])
        conn = get_db()
        occupied_count = conn.execute(
            """
            SELECT COUNT(user_id) FROM event_registration_slots
            WHERE registration_id=?
            """,
            (registration_id,),
        ).fetchone()[0]
        registration_count = conn.execute(
            "SELECT COUNT(*) FROM event_registrations WHERE event_id=?",
            (self.event_id,),
        ).fetchone()[0]
        pending_count = conn.execute(
            """
            SELECT COUNT(*) FROM event_individual_registrations
            WHERE event_id=? AND assignment_status='pending'
            """,
            (self.event_id,),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(occupied_count, 1)
        self.assertEqual(registration_count, 1)
        self.assertEqual(pending_count, 3)

    def test_admin_remove_after_draw_resets_assignment(self):
        conn = get_db()
        for user_id, name, steam_id in (
            (self.captain_id, "Captain", "76561198000000101"),
            (self.member_id, "Member", "76561198000000102"),
        ):
            conn.execute(
                """INSERT INTO event_individual_registrations(
                       event_id, user_id, player_name, steam_id,
                       assignment_status, team_number, assigned_at
                   ) VALUES(?,?,?,?,'assigned',1,CURRENT_TIMESTAMP)""",
                (self.event_id, user_id, name, steam_id),
            )
        entry_id = conn.execute(
            """SELECT id FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.captain_id),
        ).fetchone()["id"]
        conn.commit()
        conn.close()

        self._login_admin()
        removed = self._ajax_post(
            f"/events/{self.event_id}/individual-registration/{entry_id}/remove"
        )
        self.assertEqual(removed.status_code, 200)
        conn = get_db()
        remaining = conn.execute(
            """SELECT assignment_status, team_number
               FROM event_individual_registrations WHERE event_id=?""",
            (self.event_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(remaining["assignment_status"], "pending")
        self.assertIsNone(remaining["team_number"])


if __name__ == "__main__":
    unittest.main()
