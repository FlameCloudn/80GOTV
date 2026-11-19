"""Review the original pages offline using a disposable source copy and synthetic data."""

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
    with tempfile.TemporaryDirectory(prefix="slice03-browser-", dir=scratch) as work:
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


def serve(root):
    suite = Path.cwd()
    if ((suite / ".env").exists() or suite.name != "source"
            or not suite.parent.name.startswith("slice03-browser-")
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

    from tests.test_host_operations_chain import HostOperationsChainTests
    from tests.test_host_prematch_chain import app

    class Quiet(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            pass

    case = HostOperationsChainTests("test_real_signup_roster_freeze_and_bo3_bp")
    try:
        case.setUp()
        managed = case.prepare_bo3()
        legacy = case.seed_legacy_result()
        cookie = case.site.client(admin_id=case.site.admin_id).get_cookie(app.config["SESSION_COOKIE_NAME"])
        assert cookie is not None
        with make_server("127.0.0.1", 0, app, threaded=True, request_handler=Quiet) as server:
            serving = Thread(target=server.serve_forever)
            serving.start()
            try:
                payload = {
                    "base": f"http://127.0.0.1:{server.server_port}",
                    "output": str(root / "output/ui-audit/slice-03"),
                    "playwright": str(root / "node_modules/playwright"),
                    "cookie": {"name": cookie.key, "value": cookie.value},
                    "managed_match": f"/matches/{managed['match_id']}",
                    "admin_match": f"/admin/matches/edit/{managed['match_id']}",
                    "legacy_match": f"/matches/{legacy['match_id']}",
                    "legacy_player": f"/players/{legacy['player_id']}",
                }
                voters = {}
                for device, account in zip(("desktop", "mobile"), case.site.accounts[2:4], strict=True):
                    voter = case.site.client(user_id=account).get_cookie(app.config["SESSION_COOKIE_NAME"])
                    assert voter is not None
                    voters[device] = {"name": voter.key, "value": voter.value}
                payload["voters"] = voters
                driver = Path(__file__).with_suffix(".cjs")
                before = subprocess.run(["node", str(driver)], input=json.dumps(payload), text=True,
                                        timeout=180, check=False).returncode
                if before:
                    return before
                for account in case.site.accounts[2:4]:
                    vote = case.site.db.execute(
                        "SELECT voted_for,scored,points_earned FROM match_votes WHERE match_id=? AND user_id=?",
                        (managed["match_id"], account),
                    ).fetchone()
                    assert tuple(vote) == ("t1", 0, 0)
                completed = case.complete_bo3(managed)
                for account in case.site.accounts[2:4]:
                    vote = case.site.db.execute(
                        "SELECT scored,points_earned FROM match_votes WHERE match_id=? AND user_id=?",
                        (managed["match_id"], account),
                    ).fetchone()
                    assert tuple(vote) == (1, 8)
                players = {}
                for label, player_id in (("outgoing", managed["outgoing"]),
                                         ("incoming", managed["incoming"]),
                                         ("anchor", completed["anchor"])):
                    name = case.site.db.execute(
                        "SELECT nickname FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0]
                    players[label] = {"url": f"/players/{player_id}", "name": name}
                payload.update(mode="completed", players=players)
                return subprocess.run(["node", str(driver)], input=json.dumps(payload), text=True,
                                      timeout=180, check=False).returncode
            finally:
                server.shutdown()
                serving.join()
    finally:
        case.doCleanups()


if __name__ == "__main__":
    raise SystemExit(serve(Path(sys.argv[2])) if sys.argv[1:] and sys.argv[1] == "--child"
                     else isolated_run(Path(__file__).resolve().parents[3]))
