"""A real legacy form, clock process, administrator, Jinja view and broadcast read in sequence."""

import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

from entrant_slice.sandbox import ROOT, connect, create_app, initialize


def body(response) -> dict:
    value = response.get_json()
    if not isinstance(value, dict):
        raise AssertionError(f"预期 JSON 对象，实际 HTTP {response.status_code}")
    return value


class EntrantHttpWorkflow(unittest.TestCase):
    def test_old_forms_to_unattended_deadline_to_confirmed_reads(self):
        if "--inside" not in sys.argv:
            trial = subprocess.run(
                [sys.executable, "-B", "-m", "tests.test_entrant_slice_http", "--inside"],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=95,
            )
            self.assertEqual(trial.returncode, 0, trial.stderr)
            return
        import secrets

        from PIL import Image
        from werkzeug.security import generate_password_hash

        with tempfile.TemporaryDirectory() as directory:
            workspace = initialize(Path(directory))
            app = create_app(workspace)
            with closing(connect(workspace)) as db:
                from tests.entrant_slice_fixtures import seed_registrants

                people = seed_registrants(db, [100] * 13)
                db.execute("UPDATE users SET is_bashizhong_student=0")
                password = secrets.token_urlsafe(18)
                db.execute(
                    "INSERT INTO admins(username,password_hash) VALUES('local-official',?)",
                    (generate_password_hash(password),),
                )
            staff = app.test_client()
            csrf = body(staff.get("/auth/csrf-token"))["csrf_token"]
            login = staff.post(
                "/login",
                data={"username": "local-official", "password": password, "csrf_token": csrf},
            )
            self.assertEqual(login.status_code, 302)
            staff_headers = {"X-CSRF-Token": body(staff.get("/auth/csrf-token"))["csrf_token"]}
            self.assertEqual(
                staff.post(
                    "/admin/entrant-slice/events",
                    json={"name": "错误时间", "slug": "bad-date", "registration_deadline": 2**70},
                    headers=staff_headers,
                ).status_code,
                400,
            )
            deadline = int(time.time()) + 15
            response = staff.post(
                "/admin/entrant-slice/events",
                json={
                    "name": "隔离验收赛",
                    "slug": "end-to-end-cup",
                    "registration_deadline": deadline,
                },
                headers=staff_headers,
            )
            self.assertEqual(response.status_code, 201, response.text)
            event = body(response)["event_id"]
            clients = []
            for person in people:
                client = app.test_client()
                with client.session_transaction() as auth:
                    auth["user_id"] = person.account_id
                token = body(client.get("/auth/csrf-token"))["csrf_token"]
                clients.append(
                    (client, {"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": token})
                )

            def submit(index, suffix, fields=None):
                return clients[index][0].post(
                    f"/events/{event}/{suffix}", data=fields or {}, headers=clients[index][1]
                )

            icon = BytesIO()
            Image.new("RGB", (32, 32), (30, 120, 80)).save(icon, format="PNG")
            icon.seek(0)
            self.assertEqual(
                submit(
                    0,
                    "register",
                    {"my_slot": "0", "team_name": "参赛方甲", "team_logo": (icon, "sample.png")},
                ).status_code,
                302,
            )
            with closing(connect(workspace)) as db:
                group, logo = db.execute(
                    "SELECT registration_group_id,logo FROM registration_group"
                ).fetchone()
            self.assertTrue(
                staff.get(f"/static/uploads/team_logos/{logo}").data.startswith(b"\x89PNG")
            )
            for slot in (1, 2):
                self.assertTrue(body(submit(slot, f"join/{group}/{slot}"))["success"])
            for index in range(3, 11):
                self.assertTrue(body(submit(index, "register-individual"))["success"])
            self.assertEqual(submit(3, "register-individual").status_code, 409)
            self.assertTrue(body(submit(11, "register-substitute"))["success"])
            inspect = f"/admin/entrant-slice/events/{event}"
            self.assertEqual(body(staff.get(inspect))["entrants"], [])
            self.assertEqual(
                clients[1][0]
                .post(
                    inspect + "/confirm-initial",
                    json={"event_entrant_ids": [1], "expected_revision": 1},
                    headers=clients[1][1],
                )
                .status_code,
                403,
            )
            # No request is sent until the separate clock has committed the entire batch.
            watcher = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "entrant_slice",
                    "--workspace",
                    str(workspace),
                    "watch",
                    "--interval",
                    "0.15",
                ],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                end = time.monotonic() + 35
                formed = None
                while time.monotonic() < end:
                    with closing(connect(workspace)) as db:
                        formed = db.execute(
                            "SELECT * FROM formation_batch WHERE event_id=?", (event,)
                        ).fetchone()
                    if formed or watcher.poll() is not None:
                        break
                    time.sleep(0.12)
                assert formed is not None, "独立进程未在截止后完成分队"
                self.assertGreaterEqual(formed["formed_at"], deadline)
            finally:
                watcher.terminate()
                watcher.communicate(timeout=10)
            self.assertEqual(submit(12, "register-individual").status_code, 409)
            before = body(staff.get(inspect))
            ids = [r["event_entrant_id"] for r in before["entrants"]]
            self.assertEqual(len(ids), 2)
            self.assertEqual(
                {c["registration_origin"] for c in before["reserve_candidates"]},
                {"individual", "independent_reserve"},
            )
            command = {"event_entrant_ids": ids, "expected_revision": before["formation_revision"]}
            confirmed = staff.post(
                inspect + "/confirm-initial", json=command, headers=staff_headers
            )
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            self.assertEqual(
                staff.post(inspect + "/confirm-initial", json=command, headers=staff_headers).json,
                confirmed.json,
            )
            self.assertEqual(
                staff.post(
                    inspect + "/confirm-initial",
                    json={**command, "player_ids": [999]},
                    headers=staff_headers,
                ).status_code,
                400,
            )
            after = body(staff.get(inspect))
            self.assertTrue(
                all(
                    r["initial_player_ids"] == r["current_player_ids"]
                    and len(r["initial_player_ids"]) == 5
                    and r["confirmed_by"]
                    for r in after["entrants"]
                )
            )
            page = app.test_client().get("/events/end-to-end-cup")
            self.assertEqual(page.status_code, 200)
            self.assertIn("参赛方甲", page.text)
            report = body(app.test_client().get(f"/api/broadcast/events/{event}"))["event"]
            self.assertEqual(sorted(len(t["players"]) for t in report["teams"]), [5, 5])
            with closing(connect(workspace)) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM event_registrations").fetchone()[0], 0
                )
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    if "--inside" in sys.argv:
        unittest.main(argv=[sys.argv[0]])
    else:
        unittest.main()
