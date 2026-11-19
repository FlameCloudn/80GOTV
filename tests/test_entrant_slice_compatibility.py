"""Real legacy HTML, Flask JSON and desktop import with a separate SQLite sandbox."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections import defaultdict
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTOR = ROOT / "tests/acceptance/slice-01-event-entrant/legacy_director_replay.cjs"
AJAX = {"X-Requested-With": "XMLHttpRequest"}


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = set()
        self.labels = defaultdict(list)
        self.forms = {}
        self.action = ""
        self.label = ""
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "form":
            self.action = attrs.get("action", "")
            self.forms[self.action] = ""
        elif tag == "input" and self.action and attrs.get("name") == "csrf_token":
            self.forms[self.action] = attrs["value"]
        elif tag == "span":
            self.label = next(
                (
                    c
                    for c in (attrs.get("class") or "").split()
                    if c in {"event-reg-team-name", "team-badge-name"}
                ),
                "",
            )

    def handle_endtag(self, tag):
        if tag == "form":
            self.action = ""
        if tag == "span":
            self.label = ""

    def handle_data(self, data):
        if self.label and data.strip():
            self.labels[self.label].append(data.strip())


def _steam(player_id):
    return str(76561198080000000 + player_id)


def _replay(workspace):
    # Only the dedicated sandbox is allowed to initialize the legacy modules.
    from entrant_slice import formation, registration
    from entrant_slice.legacy import _projected_connection
    from entrant_slice.sandbox import connect, create_app, initialize
    from entrant_slice.storage import write

    test = unittest.TestCase()
    initialize(workspace)
    app = create_app(workspace)
    now = int(time.time())
    with closing(connect(workspace)) as db, write(db):
        db.execute(
            "INSERT INTO admins(id,username,password_hash) VALUES(1,'fixture-admin','not-a-password')"
        )
        for player_id in (*range(1, 14), 21):
            db.execute(
                "INSERT INTO players(id,nickname,steam_id,cs2_playtime_minutes) VALUES(?,?,?,?)",
                (player_id, f"合成选手{player_id:02}", _steam(player_id), 1000 * player_id),
            )
            db.execute(
                """INSERT INTO users(id,username,password_hash,steam_id64,email,is_bashizhong_student)
                          VALUES(?,?,'not-a-password',?,?,0)""",
                (
                    player_id,
                    f"合成选手{player_id:02}",
                    _steam(player_id),
                    f"private-fixture-{player_id}@example.invalid",
                ),
            )
        old_id = db.execute(
            "INSERT INTO events(name,slug,start_date,registration_open) VALUES(?,?,?,1)",
            ("旧示例届", "legacy-fixture", "2099-01-03"),
        ).lastrowid
        db.execute(
            "INSERT INTO event_registrations(id,event_id,team_name,creator_user_id) VALUES(31,?,?,21)",
            (old_id, "旧示例队"),
        )
        db.execute(
            """INSERT INTO event_registration_slots(registration_id,slot_index,user_id,player_name,steam_id)
                       VALUES(31,0,21,'合成选手21',?)""",
            (_steam(21),),
        )
        open_id = registration.create_event(
            db, "尚无队伍的示例届", "empty-fixture", now + 500, admin_id=1, now=now
        )
        empty_closed_id = registration.create_event(
            db, "仅候补的示例届", "empty-cutoff-fixture", now - 60, admin_id=1, now=now - 120
        )
        db.execute("UPDATE events SET start_date='2000-01-01' WHERE id=?", (empty_closed_id,))
        event_id = registration.create_event(
            db, "新示例届", "entrant-fixture", now - 60, admin_id=1, now=now - 120
        )
        db.execute("UPDATE events SET start_date='2099-01-02' WHERE id=?", (event_id,))
        db.execute(
            "INSERT INTO event_slug_aliases(slug,event_id) VALUES('historical-fixture',?)",
            (event_id,),
        )
        db.execute(
            "INSERT INTO event_registrations(id,event_id,team_name,creator_user_id) VALUES(47,?,?,21)",
            (event_id, "切片不应混读的旧影子队"),
        )
        group = registration.create_group(
            db,
            event_id,
            1,
            "新示例临时队",
            now=now - 120,
            reservations={4: ("合成预留人", _steam(5))},
        )
    public = app.test_client()
    open_client = app.test_client()
    with open_client.session_transaction() as session:
        session["user_id"] = 12
    open_url = f"/events/{open_id}/register-substitute"
    html = open_client.get("/events/empty-fixture")
    test.assertEqual(html.status_code, 200)
    markup = Markup(html.text)
    test.assertIn(open_url, markup.forms)
    test.assertEqual(public.post(open_url, headers=AJAX).status_code, 401)
    test.assertEqual(open_client.post(open_url, headers=AJAX).status_code, 403)
    signed = open_client.post(open_url, data={"csrf_token": markup.forms[open_url]}, headers=AJAX)
    test.assertEqual(signed.status_code, 200, signed.get_json())
    test.assertTrue(signed.get_json()["success"])
    test.assertIn("合成选手12", signed.get_json()["html"])
    test.assertIn(open_url, Markup(signed.get_json()["html"]).forms)
    with closing(_projected_connection(lambda: connect(workspace))) as db:
        first_reserve = db.execute(
            "SELECT team_number, assigned_at, created_at FROM event_individual_registrations WHERE event_id=?",
            (open_id,),
        ).fetchone()
        test.assertIsNone(first_reserve["team_number"])
        test.assertTrue(first_reserve["assigned_at"])
        test.assertEqual(first_reserve["assigned_at"], first_reserve["created_at"])
    actor = app.test_client()
    with actor.session_transaction() as session:
        session["user_id"] = 13
    test.assertIn(
        f"/events/{open_id}/register-individual",
        Markup(actor.get("/events/empty-fixture").text).forms,
    )
    empty_closed_page = actor.get("/events/empty-cutoff-fixture")
    test.assertEqual(empty_closed_page.status_code, 200)
    test.assertIn("进行中", empty_closed_page.text)
    empty_closed = Markup(empty_closed_page.text)
    test.assertIn(f"/events/{empty_closed_id}/register-substitute", empty_closed.forms)
    test.assertNotIn(f"/events/{empty_closed_id}/register-individual", empty_closed.forms)
    test.assertNotIn("regOpenButton", empty_closed.ids)

    path = f"/api/broadcast/events/{event_id}"
    draft = public.get(path).get_json()["event"]
    test.assertGreater(group, 47)
    test.assertEqual([t["name"] for t in draft["teams"]], ["新示例临时队"])
    test.assertEqual(draft["teams"][0]["players"][4]["role"], "reserved")
    test.assertEqual(draft["teams"][0]["players"][4]["slot"], 5)
    cutoff = actor.get("/events/entrant-fixture")
    test.assertEqual(cutoff.status_code, 200)
    test.assertNotIn("报名开放中", cutoff.text)
    test.assertNotIn("regOpenButton", Markup(cutoff.text).ids)
    test.assertIn(f"/events/{event_id}/register-substitute", Markup(cutoff.text).forms)
    for alias in (f"/events/{event_id}", "/events/historical-fixture"):
        redirect = public.get(alias)
        test.assertEqual(
            (redirect.status_code, redirect.location), (301, "/events/entrant-fixture")
        )

    with closing(connect(workspace)) as db, write(db):
        for slot in range(1, 5):
            registration.join_group(db, event_id, group, slot + 1, slot, now=now - 120)
        for player_id in range(6, 11):
            registration.enroll(db, event_id, player_id, "individual", now=now - 120)
        registration.enroll(
            db, event_id, 11, "independent_reserve", preferred_group_id=group, now=now - 120
        )
        registration.enroll(db, event_id, 12, "independent_reserve", now=now - 120)
        batch = formation.form_due_event(db, event_id, now=now)
    formed = public.get(path).get_json()["event"]
    test.assertEqual((formed["team_count"], formed["substitute_count"]), (2, 2))
    test.assertEqual([p["id"] for p in formed["teams"][0]["players"]], [1, 2, 3, 4, 5])
    test.assertEqual({p["id"] for p in formed["teams"][1]["players"]}, set(range(6, 11)))
    test.assertEqual(formed["substitutes"][0]["preferred_registration_id"], group)
    test.assertEqual(formed["substitutes"][0]["preferred_team_name"], "新示例临时队")
    with closing(_projected_connection(lambda: connect(workspace))) as db:
        assignments = db.execute(
            "SELECT assignment_status,team_number FROM event_individual_registrations WHERE event_id=? ORDER BY user_id",
            (event_id,),
        ).fetchall()
        test.assertEqual(
            [tuple(row) for row in assignments],
            [("assigned", formed["teams"][1]["registration_id"])] * 5 + [("reserve", None)] * 2,
        )
    staged_html = Markup(public.get("/events/entrant-fixture").text)
    test.assertEqual(
        set(staged_html.labels["event-reg-team-name"]), {"新示例临时队", "个人报名队 1"}
    )
    test.assertEqual(staged_html.labels["team-badge-name"], [])

    late_url = f"/events/{event_id}/register-substitute"
    late = actor.post(
        late_url, data={"csrf_token": Markup(cutoff.text).forms[late_url]}, headers=AJAX
    )
    test.assertEqual(late.status_code, 200, late.get_json())
    with closing(connect(workspace)) as db, write(db):
        registration.withdraw(db, event_id, 12, now=now)
        confirmed = formation.confirm_initial_rosters(
            db,
            event_id,
            batch["entrant_ids"],
            expected_revision=batch["formation_revision"],
            admin_id=1,
            now=now,
        )
        first = batch["entrant_ids"][0]
        assigned = formation.assign_reserve(
            db,
            event_id,
            first,
            11,
            expected_revision=confirmed["formation_revision"],
            admin_id=1,
            reason="合成优先候补",
            now=now,
        )
        formation.replace_before_series(
            db,
            event_id,
            first,
            5,
            11,
            expected_revision=assigned["formation_revision"],
            admin_id=1,
            reason="合成赛前换人",
            now=now,
        )
        registration.archive_event(db, event_id, admin_id=1, now=now)

    archived = public.get("/events/entrant-fixture")
    test.assertEqual(archived.status_code, 200)
    markup = Markup(archived.text)
    test.assertNotIn("eventRegistrationSection", markup.ids)
    test.assertEqual(set(markup.labels["team-badge-name"]), {"新示例临时队", "个人报名队 1"})
    test.assertIn("合成选手11", archived.text)
    test.assertNotIn("合成选手05", archived.text)
    test.assertNotIn("private-fixture-", archived.text)
    test.assertEqual(public.get("/events/legacy-fixture").status_code, 200)
    test.assertIn(
        "旧示例队", Markup(public.get("/events/legacy-fixture").text).labels["event-reg-team-name"]
    )
    test.assertEqual(
        actor.post(
            f"/events/{old_id}/register-substitute",
            data={"csrf_token": Markup(cutoff.text).forms[late_url]},
            headers=AJAX,
        ).status_code,
        404,
    )

    responses = {}
    for url in (
        "/api/broadcast/matches",
        "/api/broadcast/events",
        f"/api/broadcast/events/{old_id}",
        path,
    ):
        response = public.get(url)
        test.assertEqual(response.status_code, 200)
        test.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        test.assertNotIn("private-fixture-", response.text)
        responses[url] = {"status": response.status_code, "json": response.get_json()}
    current = responses[path]["json"]["event"]
    test.assertEqual(current["teams"][0]["source_id"], f"registration-{group}")
    test.assertIsNone(current["teams"][0]["id"])
    test.assertEqual([p["id"] for p in current["teams"][0]["players"]], [1, 2, 3, 4, 11])
    test.assertEqual([p["id"] for p in current["substitutes"]], [13])
    legacy = responses[f"/api/broadcast/events/{old_id}"]["json"]["event"]
    test.assertEqual(legacy["teams"][0]["source_id"], "registration-31")
    test.assertEqual(legacy["teams"][0]["players"][0]["steam_id"], _steam(21))
    not_found = public.get("/api/broadcast/events/99999")
    test.assertEqual(not_found.status_code, 404)
    test.assertEqual(not_found.get_json(), {"ok": False, "event": None, "error": "赛事不存在"})
    with closing(connect(workspace)) as db:
        roster = formation.get_roster(db, event_id, first)
        test.assertEqual(roster["initial_player_ids"], [1, 2, 3, 4, 5])
        test.assertEqual(roster["current_player_ids"], [1, 2, 3, 4, 11])
        test.assertEqual(
            [r[0] for r in db.execute("SELECT id FROM event_registrations ORDER BY id")], [31, 47]
        )
        test.assertEqual(
            db.execute("SELECT COUNT(*) FROM event_individual_registrations").fetchone()[0], 0
        )
        test.assertEqual(db.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 0)
    with closing(connect(workspace)) as db, write(db):
        edit_group = registration.create_group(
            db, open_id, 1, "管理员操作示例队", reservations={1: ("待核位置", _steam(2))}, now=now
        )
    admin_client = app.test_client()
    with admin_client.session_transaction() as session:
        session["admin_id"] = 1
    open_admin = Markup(admin_client.get("/events/empty-fixture").text)
    slot_path = f"/events/{open_id}/registrations/{edit_group}/slots"
    test.assertNotIn(f"{slot_path}/0/update", open_admin.forms)
    test.assertIn(f"{slot_path}/1/update", open_admin.forms)
    legacy_admin = Markup(admin_client.get("/events/legacy-fixture").text)
    test.assertIn(f"/events/{old_id}/registrations/31/slots/0/update", legacy_admin.forms)
    return {
        "responses": responses,
        "event_id": event_id,
        "old_id": old_id,
        "open_id": open_id,
        "group": group,
    }


class EntrantLegacyCompatibilityTest(unittest.TestCase):
    def test_actual_legacy_website_and_director(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        site = subprocess.run(
            [sys.executable, "-B", "-m", "tests.test_entrant_slice_compatibility", "--flask-json"],
            cwd=ROOT,
            env=env,
            encoding="utf-8",
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(site.returncode, 0, site.stderr)
        desktop = subprocess.run(
            ["node", "--permission", "--allow-fs-read=.", str(DIRECTOR)],
            cwd=ROOT,
            input=site.stdout,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(desktop.returncode, 0, desktop.stderr)


if __name__ == "__main__":
    if sys.argv[1:] == ["--flask-json"]:
        with tempfile.TemporaryDirectory() as directory:
            print(json.dumps(_replay(Path(directory)), ensure_ascii=True))
    else:
        unittest.main()
