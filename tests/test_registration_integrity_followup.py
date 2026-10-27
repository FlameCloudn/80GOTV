import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import app
from config import Config
from models import get_db, init_tables
from routes import events as event_routes


class RegistrationIntegrityFollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp.name, "registration.db")
        self.original_database = Config.DATABASE
        self.original_testing = app.config.get("TESTING")
        self.original_secure_cookie = app.config.get("SESSION_COOKIE_SECURE")
        self.individual_open_patch = patch(
            "routes.events._individual_registration_is_open", return_value=True
        )
        self.individual_open_patch.start()
        Config.DATABASE = self.database_path
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        init_tables()

        conn = get_db()
        self.event_id = self._create_event(conn)
        self.captain_id = self._insert_user(conn, "Captain", "76561198000000101")
        self.member_id = self._insert_user(conn, "Member", "76561198000000102")
        self.outsider_id = self._insert_user(conn, "Outsider", "76561198000000103")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.individual_open_patch.stop()
        Config.DATABASE = self.original_database
        app.config.update(
            TESTING=self.original_testing,
            SESSION_COOKIE_SECURE=self.original_secure_cookie,
        )
        self.temp.cleanup()

    @staticmethod
    def _create_event(conn, *, status="upcoming", start_date="2099-01-01", end_date="2099-01-02"):
        conn.execute(
            """INSERT INTO events(
                   name, slug, registration_open, status, start_date, end_date
               ) VALUES(?, ?, 1, ?, ?, ?)""",
            (
                "Registration Integrity",
                f"registration-integrity-{status}-{start_date}",
                status,
                start_date,
                end_date,
            ),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    @staticmethod
    def _insert_user(conn, username, steam_id):
        conn.execute(
            """INSERT INTO users(
                   username, password_hash, steam_id64, approval_status,
                   group_username, is_bashizhong_student
               ) VALUES(?,?,?,'approved',?,1)""",
            (username, generate_password_hash("test-only-password"), steam_id, username),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _create_registration(self, conn, event_id, team_name, reserved_slot=None):
        conn.execute(
            """INSERT INTO event_registrations(
                   event_id, team_name, creator_user_id, status
               ) VALUES(?,?,?,'pending')""",
            (event_id, team_name, self.captain_id),
        )
        registration_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for slot_index in range(5):
            if slot_index == 0:
                values = (self.captain_id, "Captain", "76561198000000101", 1)
            elif reserved_slot and slot_index == reserved_slot[0]:
                values = reserved_slot[1:]
            else:
                values = (None, f"位置{slot_index + 1}", "", 0)
            conn.execute(
                """INSERT INTO event_registration_slots(
                       registration_id, slot_index, user_id, player_name, steam_id,
                       filled_by_creator
                   ) VALUES(?,?,?,?,?,?)""",
                (registration_id, slot_index, *values),
            )
        return registration_id

    @staticmethod
    def _login(client, user_id, username):
        with client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session["user_id"] = user_id
            browser_session["user_username"] = username
            browser_session["csrf_token"] = "registration-csrf"

    @staticmethod
    def _ajax_post(client, path, data=None):
        payload = {"csrf_token": "registration-csrf"}
        payload.update(data or {})
        return client.post(
            path,
            data=payload,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    def test_join_rejects_all_reserved_slot_shapes_without_changing_them(self):
        reserved_slots = [
            ("player name", (1, None, "Invited Player", "", 0)),
            ("Steam ID", (1, None, "位置2", "76561198000000999", 0)),
            ("creator reservation", (1, None, "位置2", "", 1)),
        ]

        for label, reserved_slot in reserved_slots:
            with self.subTest(reservation=label):
                conn = get_db()
                registration_id = self._create_registration(
                    conn, self.event_id, f"Reserved {label}", reserved_slot
                )
                conn.commit()
                before = dict(
                    conn.execute(
                        """SELECT user_id, player_name, steam_id, filled_by_creator
                           FROM event_registration_slots
                           WHERE registration_id=? AND slot_index=1""",
                        (registration_id,),
                    ).fetchone()
                )
                conn.close()

                client = app.test_client()
                self._login(client, self.outsider_id, "Outsider")
                response = self._ajax_post(
                    client, f"/events/{self.event_id}/join/{registration_id}/1"
                )
                self.assertEqual(response.status_code, 409)
                self.assertFalse(response.get_json()["success"])

                conn = get_db()
                after = dict(
                    conn.execute(
                        """SELECT user_id, player_name, steam_id, filled_by_creator
                           FROM event_registration_slots
                           WHERE registration_id=? AND slot_index=1""",
                        (registration_id,),
                    ).fetchone()
                )
                joined = conn.execute(
                    """SELECT COUNT(*) FROM event_registration_slots s
                       JOIN event_registrations r ON r.id=s.registration_id
                       WHERE r.event_id=? AND s.user_id=?""",
                    (self.event_id, self.outsider_id),
                ).fetchone()[0]
                conn.close()
                self.assertEqual(after, before)
                self.assertEqual(joined, 0)

    def _run_serialized_race(self, second_path, *, prepare=None, second_data=None):
        conn = get_db()
        first_registration = self._create_registration(conn, self.event_id, "Race Team One")
        second_registration = self._create_registration(conn, self.event_id, "Race Team Two")
        if prepare:
            prepare(conn)
        conn.commit()
        conn.close()

        first_locked = threading.Event()
        second_lock_attempted = threading.Event()
        release_first = threading.Event()
        second_finished = threading.Event()
        results = {}
        errors = {}
        original_begin = event_routes._begin_registration_write

        def controlled_begin(connection):
            name = threading.current_thread().name
            if name == "registration-first":
                original_begin(connection)
                first_locked.set()
                if not release_first.wait(5):
                    raise TimeoutError("第一条请求没有及时释放写入锁")
            elif name == "registration-second":
                second_lock_attempted.set()
                original_begin(connection)
            else:
                original_begin(connection)

        def submit(name, path, data=None, finished=None):
            client = app.test_client()
            self._login(client, self.outsider_id, "Outsider")
            try:
                results[name] = self._ajax_post(client, path, data)
            except BaseException as exc:
                errors[name] = exc
            finally:
                if finished:
                    finished.set()

        with (
            patch("routes.events._begin_registration_write", side_effect=controlled_begin),
            patch("routes.events.rate_limit", return_value=True),
        ):
            first = threading.Thread(
                name="registration-first",
                target=submit,
                args=(
                    "first",
                    f"/events/{self.event_id}/join/{first_registration}/1",
                ),
            )
            first.start()
            first_acquired = False
            second_attempted = False
            second_blocked = False
            try:
                first_acquired = first_locked.wait(5)
                if first_acquired and second_path == "join":
                    second_path = f"/events/{self.event_id}/join/{second_registration}/1"
                if first_acquired:
                    second = threading.Thread(
                        name="registration-second",
                        target=submit,
                        args=("second", second_path, second_data, second_finished),
                    )
                    second.start()
                    second_attempted = second_lock_attempted.wait(5)
                    if second_attempted:
                        second_blocked = not second_finished.wait(0.1)
            finally:
                release_first.set()
            first.join(8)
            if "second" in locals():
                second.join(8)

        self.assertTrue(first_acquired, "第一条请求未取得写入锁")
        self.assertTrue(second_attempted, "第二条请求未尝试取得写入锁")
        self.assertTrue(
            second_blocked,
            "第一条请求仍持有写入锁时，第二条请求不应完成",
        )

        self.assertFalse(first.is_alive(), "第一条并发请求未结束")
        self.assertFalse(second.is_alive(), "第二条并发请求未结束")
        self.assertEqual(errors, {})
        self.assertEqual(results["first"].status_code, 200)
        self.assertEqual(results["second"].status_code, 409)

        conn = get_db()
        joined_slots = conn.execute(
            """SELECT registration_id, slot_index FROM event_registration_slots
               WHERE user_id=?""",
            (self.outsider_id,),
        ).fetchall()
        individual_rows = conn.execute(
            """SELECT id, assignment_status FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.outsider_id),
        ).fetchall()
        losing_slot = conn.execute(
            """SELECT user_id FROM event_registration_slots
               WHERE registration_id=? AND slot_index=1""",
            (second_registration,),
        ).fetchone()
        conn.close()
        self.assertEqual(len(joined_slots), 1)
        self.assertEqual(joined_slots[0]["registration_id"], first_registration)
        self.assertEqual(joined_slots[0]["slot_index"], 1)
        self.assertIsNone(losing_slot["user_id"])
        if second_path.endswith("register-individual") or second_path.endswith(
            "register-substitute"
        ):
            self.assertEqual(individual_rows, [])
        return first_registration, second_registration

    def test_concurrent_joins_for_one_user_cannot_join_two_teams(self):
        self._run_serialized_race("join")

    def test_join_and_individual_registration_share_the_same_write_lock(self):
        self._run_serialized_race(f"/events/{self.event_id}/register-individual")

    def test_join_and_substitute_registration_share_the_same_write_lock(self):
        def add_finalized_member(conn):
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

        self._run_serialized_race(
            f"/events/{self.event_id}/register-substitute",
            prepare=add_finalized_member,
        )

    def test_substitute_registration_rejects_events_that_have_ended(self):
        ended_events = [
            ("past end date", "ongoing", "2020-01-01", "2020-01-02"),
            ("explicit completed status", "completed", "2099-01-01", "2099-01-02"),
        ]
        client = app.test_client()
        self._login(client, self.outsider_id, "Outsider")

        for label, status, start_date, end_date in ended_events:
            with self.subTest(ended_by=label):
                conn = get_db()
                event_id = self._create_event(
                    conn,
                    status=status,
                    start_date=start_date,
                    end_date=end_date,
                )
                registration_id = self._create_registration(conn, event_id, f"Finalized {label}")
                conn.execute(
                    """INSERT INTO event_individual_registrations(
                           event_id, user_id, player_name, steam_id,
                           assignment_status, team_number, assigned_at
                       ) VALUES(?,?,?,?, 'assigned', 1, CURRENT_TIMESTAMP)""",
                    (
                        event_id,
                        self.captain_id,
                        "Captain",
                        "76561198000000101",
                    ),
                )
                conn.commit()
                conn.close()

                response = self._ajax_post(client, f"/events/{event_id}/register-substitute")
                self.assertEqual(response.status_code, 409)
                self.assertFalse(response.get_json()["success"])

                conn = get_db()
                entries = conn.execute(
                    """SELECT id, assignment_status, preferred_registration_id
                       FROM event_individual_registrations
                       WHERE event_id=? AND user_id=?""",
                    (event_id, self.outsider_id),
                ).fetchall()
                team_slots = conn.execute(
                    """SELECT user_id FROM event_registration_slots
                       WHERE registration_id=? ORDER BY slot_index""",
                    (registration_id,),
                ).fetchall()
                conn.close()
                self.assertEqual(entries, [])
                self.assertEqual(team_slots[0]["user_id"], self.captain_id)

    def test_substitute_registration_remains_open_before_event_end(self):
        conn = get_db()
        registration_id = self._create_registration(conn, self.event_id, "Still Open Team")
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

        client = app.test_client()
        self._login(client, self.outsider_id, "Outsider")
        response = self._ajax_post(client, f"/events/{self.event_id}/register-substitute")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

        conn = get_db()
        entry = conn.execute(
            """SELECT assignment_status, preferred_registration_id
               FROM event_individual_registrations
               WHERE event_id=? AND user_id=?""",
            (self.event_id, self.outsider_id),
        ).fetchone()
        slot_count = conn.execute(
            """SELECT COUNT(*) FROM event_registration_slots
               WHERE registration_id=? AND user_id=?""",
            (registration_id, self.outsider_id),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(entry["assignment_status"], "reserve")
        self.assertIsNone(entry["preferred_registration_id"])
        self.assertEqual(slot_count, 0)


if __name__ == "__main__":
    unittest.main()
