"""Offline Playwright interactive & visual audit for 80GOTV Phase 3 Slice 3 frontend."""

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Thread


def isolated_run(root, entry=None):
    scratch = (root / "output/acceptance-tmp").resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="slice3-browser-", dir=scratch) as work:
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
                              ("resources", ("fonts", "maps", "map_landscapes", "placeholders", "icons", "radars"))):
            for name in names:
                p = root / parent / name
                if p.exists():
                    files.extend(item for item in p.rglob("*") if item.is_file())
        for item in files:
            if item.is_symlink() or not item.is_file() or item.resolve() != item.absolute():
                raise ValueError(f"Refused non-regular file: {item}")
            target = suite / item.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "HOME",
            "APPDATA", "LOCALAPPDATA", "SYSTEMDRIVE", "LANG", "LC_ALL", "PROGRAMFILES",
            "PROGRAMFILES(X86)", "PROGRAMW6432",
        }}
        env.update(
            TMP=work,
            TEMP=work,
            TMPDIR=work,
            FLASK_ENV="testing",
            DATABASE_PATH=str(Path(work) / "slice3.db"),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHON_DOTENV_DISABLED="1",
            PYTHONIOENCODING="utf-8",
            TURSO_URL="",
            TURSO_TOKEN="",
        )
        if sys.argv[1:2] == ["--real-demo"]:
            sample = Path(sys.argv[2]).resolve(strict=True)
            env["AUDIT_REAL_DEMO"] = str(sample)
            sys.path.insert(0, str(root))
            from utils.demo_parser import find_csda

            csda = find_csda()
            if not csda:
                raise FileNotFoundError("真实 Demo 验收需要 CSDA_PATH 或 resources/tools/csda.exe")
            env["CSDA_PATH"] = csda
        return subprocess.run(
            [sys.executable, "-B", str(entry or Path(__file__).resolve()), "--child", str(root)],
            cwd=suite,
            env=env,
            check=False,
        ).returncode


def _seed_data():
    from app import app
    from site_core.host import write
    from tests.test_frontend_slice3_operations import FrontendSlice3OperationsTests

    case = FrontendSlice3OperationsTests("test_operate_page_routes_guards_and_redirects")
    case.setUp()
    try:
        eid, mid, entrant_ids, reserve_pid = case._prepare_bo3_match()
        base = f"/admin/matches/{mid}/operations"

        # Authorize
        assert case._post(case.admin, base + "/authorize", json={}).status_code == 200
        snap = case.admin.get(base + "/panel-context").get_json()
        maps = snap["overview"]["maps"]
        home_party = snap["context"]["participants"][0]
        away_party = snap["context"]["participants"][1]
        outgoing_pid = home_party["players"][4]["id"]

        # Map 1: start, record participations for both teams, bind director session, seed demo + ready analysis, confirm 13:8
        r1 = case._post(
            case.admin,
            base + "/start",
            json={"scheduled_map_id": maps[0]["scheduled_map_id"], "evidence": "Verified Map 1 server live"},
        ).get_json()["map_run_id"]
        for p in home_party["players"]:
            case._post(
                case.admin,
                base + "/participation",
                json={
                    "map_run_id": r1,
                    "player_id": p["id"],
                    "match_participant_id": home_party["match_participant_id"],
                    "round_number": 1,
                    "side": "CT",
                    "reason": "Verified R1 pistol",
                },
            )
        for p in away_party["players"]:
            case._post(
                case.admin,
                base + "/participation",
                json={
                    "map_run_id": r1,
                    "player_id": p["id"],
                    "match_participant_id": away_party["match_participant_id"],
                    "round_number": 1,
                    "side": "T",
                    "reason": "Verified R1 pistol",
                },
            )
        case._post(
            case.admin,
            base + "/bind-director-session",
            json={"map_run_id": r1, "session_id": "dir-bo3-map1", "reason": "Verified director HUD stream"},
        )
        # Seed a real stat on player 0 so demo preview shows BOTH a clean accept AND a conflict!
        first_pid = home_party["players"][0]["id"]
        case._post(
            case.admin,
            base + "/stats",
            json={
                "map_run_id": r1,
                "player_id": first_pid,
                "scope": "all",
                "fields": {"kills": 19, "deaths": 11},
                "expected_revision": 0,
                "reason": "Initial director tally",
            },
        )
        case._post(
            case.admin,
            base + "/confirm-map",
            json={
                "scheduled_map_id": maps[0]["scheduled_map_id"],
                "map_run_id": r1,
                "score1": 13,
                "score2": 8,
                "expected_revision": 0,
                "reason": "Confirmed Map 1 final score",
            },
        )
        # Upload demo for Map 1 and insert a ready CSDA candidate analysis so browser tests Preview & Selective Adoption
        up1 = case._post(
            case.admin,
            f"/admin/matches/{mid}/api/demos",
            data={
                "scheduled_map_id": str(maps[0]["scheduled_map_id"]),
                "map_run_id": str(r1),
                "demo": (io.BytesIO(b"PBDEMS2\x00MIRAGE-RUN1-AUDIT"), "bo3_map1_mirage.dem"),
            },
        ).get_json()
        demo1_id = up1["original"]["demo_id"]

        candidate_players = {}
        for idx, p in enumerate(home_party["players"]):
            candidate_players[str(p["steam_id"])] = {
                "team": "A",
                "side_conflict": False,
                "rounds": [{"number": 1, "side": "CT"}, {"number": 2, "side": "CT"}],
                "fields": {
                    "all": {
                        "rounds_played": 21,
                        "kills": 20 if idx == 0 else (15 - idx),
                        "deaths": 11,
                        "assists": 4,
                        "damage": 1820,
                        "adr": 86.7,
                        "kast": 76.2,
                    },
                    "ct": {"rounds_played": 12, "kills": 12, "deaths": 6},
                    "t": {"rounds_played": 9, "kills": 8 if idx == 0 else 5, "deaths": 5},
                },
            }
        for idx, p in enumerate(away_party["players"]):
            candidate_players[str(p["steam_id"])] = {
                "team": "B",
                "side_conflict": False,
                "rounds": [{"number": 1, "side": "T"}, {"number": 2, "side": "T"}],
                "fields": {
                    "all": {
                        "rounds_played": 21,
                        "kills": 14 - idx,
                        "deaths": 15,
                        "assists": 3,
                        "damage": 1420,
                        "adr": 67.6,
                    }
                },
            }
        candidate_payload = {
            "map_name": "de_mirage",
            "scores": {"A": 13, "B": 8},
            "players": candidate_players,
            "unidentified_players": [],
            "round_winners": {},
            "complete_rounds": True,
        }
        with write(case.db):
            analysis_id = case.db.execute(
                """INSERT INTO demo_analyses(demo_id, status, requested_by, parser_source, finished_at, candidate_json)
                   VALUES(?, 'ready', ?, 'valve', CURRENT_TIMESTAMP, ?)""",
                (demo1_id, case.admin_id, json.dumps(candidate_payload)),
            ).lastrowid

        # Map 2: start -> upload demo -> technical replay with substitute -> replay run -> confirm 9:13
        r2_void = case._post(
            case.admin,
            base + "/start",
            json={"scheduled_map_id": maps[1]["scheduled_map_id"], "evidence": "Map 2 initial start"},
        ).get_json()["map_run_id"]
        case._post(
            case.admin,
            f"/admin/matches/{mid}/api/demos",
            data={
                "scheduled_map_id": str(maps[1]["scheduled_map_id"]),
                "map_run_id": str(r2_void),
                "demo": (io.BytesIO(b"PBDEMS2\x00INFERNO-VOID"), "bo3_map2_void.dem"),
            },
        )
        case._post(
            case.admin,
            base + "/technical-replay",
            json={
                "map_run_id": r2_void,
                "reason": "Server crashed on round 8; captain requested substitute",
                "outgoing_player_id": outgoing_pid,
                "incoming_player_id": reserve_pid,
            },
        )
        r2 = case._post(
            case.admin,
            base + "/start",
            json={
                "scheduled_map_id": maps[1]["scheduled_map_id"],
                "previous_map_run_id": r2_void,
                "evidence": "Map 2 rematch live with substitute",
            },
        ).get_json()["map_run_id"]
        case._post(
            case.admin,
            base + "/confirm-map",
            json={
                "scheduled_map_id": maps[1]["scheduled_map_id"],
                "map_run_id": r2,
                "score1": 9,
                "score2": 13,
                "expected_revision": 0,
                "reason": "Confirmed Map 2 rematch score",
            },
        )

        # Map 3: start (carries substitute) -> confirm 13:10 (explicitly NOT settled yet so browser clicks Settle!)
        r3 = case._post(
            case.admin,
            base + "/start",
            json={"scheduled_map_id": maps[2]["scheduled_map_id"], "evidence": "Map 3 decider live"},
        ).get_json()["map_run_id"]
        case._post(
            case.admin,
            base + "/confirm-map",
            json={
                "scheduled_map_id": maps[2]["scheduled_map_id"],
                "map_run_id": r3,
                "score1": 13,
                "score2": 10,
                "expected_revision": 0,
                "reason": "Confirmed Map 3 decider score",
            },
        )

        # Create downstream Final match & link winner
        downstream = case._post(
            case.admin,
            f"/admin/events/{eid}/operations/bracket",
            json={"stage": "总决赛", "bo_format": "BO1"},
        ).get_json()
        target_mid = downstream["match_id"]
        case._post(
            case.admin,
            base + "/bracket-link",
            json={"outcome": "winner", "target_match_id": target_mid, "target_side": "home"},
        )

        # Clear accumulated setup flashes before passing session cookie to Playwright
        case.admin.get("/admin/matches")
        match_slug = case.db.execute("SELECT slug FROM matches WHERE id=?", (mid,)).fetchone()["slug"]
        cookie = case.admin.get_cookie(app.config["SESSION_COOKIE_NAME"])
        viewer = case._client(user_id=case.accounts[-1])
        viewer_cookie = viewer.get_cookie(app.config["SESSION_COOKIE_NAME"])
        return case, app, cookie, {
            "eid": eid,
            "mid": mid,
            "match_slug": match_slug or str(mid),
            "target_mid": target_mid,
            "demo1_id": demo1_id,
            "analysis_id": analysis_id,
            "r1": r1,
            "first_pid": first_pid,
            "second_pid": home_party["players"][1]["id"],
            "viewer_cookie": {"name": viewer_cookie.key, "value": viewer_cookie.value},
            "real_demo": os.environ.get("AUDIT_REAL_DEMO"),
        }
    except Exception:
        case.doCleanups()
        raise


def serve(root, *, seed_data=_seed_data, driver=None, output_name="slice-03-continuation"):
    suite = Path.cwd()
    if ((suite / ".env").exists() or suite.name != "source"
            or not suite.parent.name.startswith("slice3-browser-")
            or Path(os.environ["DATABASE_PATH"]).parent != suite.parent):
        raise SystemExit("Must run inside isolated temp copy.")
    sys.path.insert(0, str(suite))
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            raise OSError("Offline audit blocks external network")
        return original_connect(sock, address)

    socket.socket.connect = local_only
    from werkzeug.serving import WSGIRequestHandler, make_server

    class Quiet(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            pass

    case, app, cookie, ids = seed_data()
    try:
        with make_server("127.0.0.1", 0, app, threaded=True, request_handler=Quiet) as server:
            serving = Thread(target=server.serve_forever)
            serving.start()
            try:
                payload = {
                    "base": f"http://127.0.0.1:{server.server_port}",
                    "output": str(root / "output/ui-audit" / output_name),
                    "playwright": str(root / "node_modules/playwright"),
                    "cookie": {"name": cookie.key, "value": cookie.value},
                    **ids,
                }
                if driver is None:
                    driver = Path(__file__).with_suffix(".cjs")
                return subprocess.run(
                    ["node", str(driver)],
                    input=json.dumps(payload),
                    text=True,
                    timeout=900,
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
