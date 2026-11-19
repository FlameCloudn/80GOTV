"""Offline Playwright English-mode audit for public and admin 80GOTV pages."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Thread


def isolated_run(root):
    scratch = (root / "output/acceptance-tmp").resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="i18n-browser-", dir=scratch) as work:
        suite = Path(work) / "source"
        suite.mkdir()
        files = list(root.glob("*.py"))
        for name in ("blueprints", "routes", "services", "utils", "tests", "scripts", "site_core", "entrant_slice"):
            files.extend((root / name).rglob("*.py"))
        for name in ("site_core", "entrant_slice"):
            files.extend((root / name).rglob("*.sql"))
        for name, pattern in (("templates", "*.html"), ("static/css", "*.css"), ("static/js", "*.js")):
            files.extend((root / name).rglob(pattern))
        files.append(root / "static/favicon.ico")
        for parent, names in (("static", ("logos", "fonts", "icons", "vendor")),
                              ("resources", ("fonts", "maps", "map_landscapes", "placeholders"))):
            for name in names:
                files.extend(item for item in (root / parent / name).rglob("*") if item.is_file())
        for item in files:
            if item.is_symlink() or not item.is_file() or item.resolve() != item.absolute():
                raise ValueError(f"未复制链接或非普通文件：{item}")
            target = suite / item.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "HOME",
            "APPDATA", "LOCALAPPDATA", "SYSTEMDRIVE", "LANG", "LC_ALL", "PROGRAMFILES",
            "PROGRAMFILES(X86)", "PROGRAMW6432",
        }}
        env.update(TMP=work, TEMP=work, TMPDIR=work, FLASK_ENV="testing",
                   DATABASE_PATH=str(Path(work) / "initial.db"), PYTHONDONTWRITEBYTECODE="1",
                   PYTHON_DOTENV_DISABLED="1", PYTHONIOENCODING="utf-8", TURSO_URL="", TURSO_TOKEN="")
        return subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--child", str(root)],
                              cwd=suite, env=env, check=False).returncode


def _seed_data():
    import time
    from datetime import date, timedelta
    from app import app
    from site_core.host import write
    from tests.test_frontend_admin_workflow import FrontendAdminWorkflowTests

    case = FrontendAdminWorkflowTests("test_event_admin_pages_enable_disable_and_blockers")
    case.setUp()
    try:
        return _seed_inner(case, app)
    except Exception:
        case.doCleanups()
        raise


def _seed_inner(case, app):
    import time
    from datetime import date, timedelta
    from site_core.host import write
    now = int(time.time())
    start_day = (date.today() + timedelta(days=1)).isoformat()
    end_day = (date.today() + timedelta(days=10)).isoformat()

    # Event A: due managed event with reservations
    eid_a, _ = case._prepare_managed_match()
    with write(case.db):
        case.db.execute(
            "UPDATE event_registration_control SET registration_deadline=? WHERE event_id=?",
            (now - 60, eid_a),
        )

    # Event B: formed, confirmed initial rosters, pre-series replace, reserves, unfrozen + frozen matches
    extra_accounts = []
    extra_players = []
    with write(case.db):
        for idx in range(20, 26):
            nick = f"ReserveSub{idx}"
            steam = str(76561199002200000 + idx)
            uid = case.db.execute(
                """INSERT INTO users(username,email,password_hash,steam_id64,approval_status,
                           group_username,is_bashizhong_student)
                   VALUES(?,?,'disabled',?,'approved',?,1)""",
                (f"res{idx}", f"res{idx}@example.invalid", steam, nick),
            ).lastrowid
            pid = case.db.execute(
                "INSERT INTO players(nickname,steam_id,cs2_playtime_minutes,is_bashizhong_student) VALUES(?,?,?,1)",
                (nick, steam, 500 + idx * 10),
            ).lastrowid
            extra_accounts.append(uid)
            extra_players.append(pid)

    assert case.post(
        case.admin,
        "/admin/events/add",
        data={
            "name": "Spring Cup En Audit",
            "short_name": "SPRG",
            "slug": "spring-cup-audit",
            "start_date": start_day,
            "end_date": end_day,
            "registration_deadline": str(now + 7200),
        },
    ).status_code == 302
    eid_b = case.db.execute("SELECT id FROM events WHERE short_name='SPRG'").fetchone()["id"]
    with write(case.db):
        b_accounts = []
        for idx in range(10):
            nick = f"LongPlayer{idx + 1:02}"
            steam = str(76561199003300000 + idx)
            uid = case.db.execute(
                """INSERT INTO users(username,email,password_hash,steam_id64,approval_status,
                           group_username,is_bashizhong_student)
                   VALUES(?,?,'disabled',?,'approved',?,1)""",
                (f"buser{idx}", f"b{idx}@example.invalid", steam, nick),
            ).lastrowid
            case.db.execute(
                "INSERT INTO players(nickname,steam_id,cs2_playtime_minutes,is_bashizhong_student) VALUES(?,?,?,1)",
                (nick, steam, 700 + idx * 20),
            )
            b_accounts.append(uid)

    b_clients = [case.client(user_id=u) for u in b_accounts]
    assert case.post(
        b_clients[0],
        f"/events/{eid_b}/register",
        data={"my_slot": 0, "team_name": "Alpha Long Mixed Roster Name"},
    ).status_code == 302
    reg_b = case.db.execute("SELECT id FROM event_registrations WHERE event_id=?", (eid_b,)).fetchone()["id"]
    for slot in range(1, 5):
        assert case.post(b_clients[slot], f"/events/{eid_b}/join/{reg_b}/{slot}").get_json()["success"]
    for c in b_clients[5:]:
        assert case.post(c, f"/events/{eid_b}/register-individual").get_json()["success"]
    for u in extra_accounts:
        assert case.post(case.client(user_id=u), f"/events/{eid_b}/register-substitute").get_json()["success"]

    with write(case.db):
        case.db.execute(
            "UPDATE event_registration_control SET registration_deadline=? WHERE event_id=?",
            (now - 60, eid_b),
        )
    assert case.post(case.admin, f"/admin/events/{eid_b}/registration-control/form-due", json={}).status_code == 200
    ctrl = case.admin.get(f"/admin/events/{eid_b}/registration-control").get_json()
    eids_b = [e["event_entrant_id"] for e in ctrl["entrants"]]
    assert case.post(
        case.admin,
        f"/admin/events/{eid_b}/registration-control/confirm-initial",
        json={"event_entrant_ids": eids_b, "expected_revision": ctrl["formation_revision"]},
    ).status_code == 200

    ctrl = case.admin.get(f"/admin/events/{eid_b}/registration-control").get_json()
    out_pid = ctrl["entrants"][0]["current_player_ids"][4]
    in_pid = extra_players[0]
    assert case.post(
        case.admin,
        f"/admin/events/{eid_b}/registration-control/assign-reserve",
        json={
            "event_entrant_id": eids_b[0],
            "player_id": in_pid,
            "expected_revision": ctrl["formation_revision"],
            "reason": "Bench slot assigned",
            "excluded_candidates": {},
        },
    ).status_code == 200
    ctrl = case.admin.get(f"/admin/events/{eid_b}/registration-control").get_json()
    assert case.post(
        case.admin,
        f"/admin/events/{eid_b}/registration-control/replace-before-series",
        json={
            "event_entrant_id": eids_b[0],
            "outgoing_player_id": out_pid,
            "incoming_player_id": in_pid,
            "expected_revision": ctrl["formation_revision"],
            "reason": "Pre-match swap",
        },
    ).status_code == 200

    future_match_time = (date.today() + timedelta(days=4)).isoformat() + " 20:00"
    assert case.post(
        case.admin,
        "/admin/matches/add",
        data={
            "event_id": str(eid_b),
            "match_time": future_match_time,
            "bo_format": "BO3",
            "bp_password": "secretbp",
            "side1_type": "entrant",
            "side1_id": str(eids_b[0]),
            "side2_type": "entrant",
            "side2_id": str(eids_b[1]),
        },
    ).status_code == 302
    mid_b = case.db.execute("SELECT id FROM matches WHERE event_id=?", (eid_b,)).fetchone()["id"]

    # Second managed match frozen for BP room audit
    assert case.post(
        case.admin,
        "/admin/matches/add",
        data={
            "event_id": str(eid_b),
            "match_time": (date.today() + timedelta(days=5)).isoformat() + " 20:00",
            "bo_format": "BO3",
            "bp_password": "secretbp",
            "side1_type": "entrant",
            "side1_id": str(eids_b[0]),
            "side2_type": "entrant",
            "side2_id": str(eids_b[1]),
        },
    ).status_code == 302
    mid_bp = case.db.execute(
        "SELECT id FROM matches WHERE event_id=? AND id<>?", (eid_b, mid_b)
    ).fetchone()["id"]
    freeze_res = case.post(case.admin, f"/admin/matches/{mid_bp}/freeze-rosters")
    assert freeze_res.status_code in (200, 302), f"Freeze failed: {freeze_res.status_code} {freeze_res.get_data(as_text=True)}"

    # Completed legacy match + stats + news + forum + pending user + feedback + test match
    past_day = (date.today() - timedelta(days=2)).isoformat() + " 19:00"
    other_club = case.db.execute("SELECT team2_id FROM matches WHERE id=?", (case.legacy_match_id,)).fetchone()[0]
    with write(case.db):
        mid_done = case.db.execute(
            """INSERT INTO matches(event_id,team1_id,team2_id,team1_score,team2_score,match_time,bo_format,
                       status,map1,map1_t1,map1_t2,map1_picked_by,bp_process,slug)
               VALUES(?,?,?,1,0,?,'BO1','completed','Mirage',13,9,'t1','Team1 removed Inferno\nMirage was left over','done-mirage')""",
            (case.legacy_event_id, case.club_id, other_club, past_day),
        ).lastrowid
        mid_test = case.db.execute(
            """INSERT INTO matches(event_id,match_time,bo_format,status,is_test_mode,slug)
               VALUES(?,?,'BO1','upcoming',1,'test-mode-match')""",
            (case.legacy_event_id, future_match_time),
        ).lastrowid
        for idx, pid in enumerate(case.player_ids[:5]):
            case.db.execute(
                """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,kills,deaths,assists,
                           adr,kpr,dpr,rating,impact,kast,headshot_percentage,first_kills,first_deaths,
                           enemies_flashed,flash_assists,rounds_played,rws_basic,map_name,data_source,data_status)
                   VALUES(?,?,?,1,?,?,?,85.0,0.8,0.6,1.18,1.12,72.5,52.0,3,1,4,2,22,12.5,'de_mirage','manual','confirmed')""",
                (mid_done, pid, case.club_id, 20 - idx, 14, 5),
            )
        case.db.execute(
            "INSERT INTO news(title,summary,content,author,publish_time,related_match_id) VALUES(?,?,?,?,?,?)",
            ("Spring Major Recap", "Summary text", "<p>Match body content</p>", "Admin", past_day, mid_done),
        )
        cat = case.db.execute("SELECT id FROM forum_categories LIMIT 1").fetchone()
        if cat:
            case.db.execute(
                "INSERT INTO forum_threads(category_id,user_id,title,content) VALUES(?,?,?,?)",
                (cat[0], case.accounts[0], "Scrim discussion", "Anyone up for Mirage?"),
            )
        case.db.execute(
            """INSERT INTO users(username,email,password_hash,steam_id64,approval_status,
                       group_username,is_bashizhong_student)
               VALUES('pending01','pending01@example.invalid','disabled','76561199009990001','pending','Pending01',1)"""
        )
        case.db.execute(
            """INSERT INTO feedback(type,content,page_url,user_id,status,admin_reply)
               VALUES('suggestion','Nice stats page','/stats',?, 'in_progress', 'Thanks!')""",
            (case.accounts[0],),
        )

    cookie = case.client(admin_id=case.admin_id, admin_username="fe-admin").get_cookie(
        app.config["SESSION_COOKIE_NAME"]
    )
    return case, app, cookie, {
        "eid_a": eid_a,
        "eid_b": eid_b,
        "legacy_eid": case.legacy_event_id,
        "mid_b": mid_b,
        "mid_bp": mid_bp,
        "mid_done": mid_done,
        "mid_test": mid_test,
        "player_id": case.player_ids[0],
        "team_id": case.club_id,
    }


def serve(root):
    suite = Path.cwd()
    if ((suite / ".env").exists() or suite.name != "source"
            or not suite.parent.name.startswith("i18n-browser-")
            or Path(os.environ["DATABASE_PATH"]).parent != suite.parent):
        raise SystemExit("只能在独立的测试副本中运行页面检查。")
    sys.path.insert(0, str(suite))
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            raise OSError("离线检查不连接外网")
        return original_connect(sock, address)

    socket.socket.connect = local_only
    from werkzeug.serving import WSGIRequestHandler, make_server

    class Quiet(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            pass

    case, app, cookie, ids = _seed_data()
    try:
        with make_server("127.0.0.1", 0, app, threaded=True, request_handler=Quiet) as server:
            serving = Thread(target=server.serve_forever)
            serving.start()
            try:
                payload = {
                    "base": f"http://127.0.0.1:{server.server_port}",
                    "output": str(root / "output/ui-audit/localization-polish"),
                    "playwright": str(root / "node_modules/playwright"),
                    "cookie": {"name": cookie.key, "value": cookie.value},
                    **ids,
                }
                driver = Path(__file__).with_suffix(".cjs")
                return subprocess.run(
                    ["node", str(driver)],
                    input=json.dumps(payload),
                    text=True,
                    timeout=240,
                    check=False,
                ).returncode
            finally:
                server.shutdown()
                serving.join()
    finally:
        case.doCleanups()


if __name__ == "__main__":
    raise SystemExit(
        serve(Path(sys.argv[2])) if sys.argv[1:] and sys.argv[1] == "--child"
        else isolated_run(Path(__file__).resolve().parents[3])
    )
