"""Start only from the isolated source copy created by the website regression runner."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from threading import Thread

from werkzeug.serving import WSGIRequestHandler, make_server


def main():
    suite = Path.cwd()
    if (
        (suite / ".env").exists()
        or suite.name != "source"
        or not suite.parent.name.startswith("isolated-baseline-")
    ):
        raise SystemExit("请通过隔离测试入口使用 --host-browser，不要在真实工作区启动。")
    if Path(os.environ["DATABASE_PATH"]).parent != suite.parent:
        raise SystemExit("未指定隔离数据库。")
    sys.path.insert(0, str(suite))
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            raise OSError("浏览器检查不连接外网")
        return original_connect(sock, address)

    socket.socket.connect = local_only
    from tests.test_host_prematch_chain import HostPrematchChainTests, app

    case = HostPrematchChainTests("test_signup_to_broadcast_in_the_original_website")

    class Quiet(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            pass

    try:
        case.setUp()
        mid = case.prepare_through_host()
        cookie = case.client(admin_id=case.admin_id).get_cookie(app.config["SESSION_COOKIE_NAME"])
        assert cookie is not None
        display = case.visitor.get(f"/api/broadcast/matches/{mid}").get_json()["match"]
        open_id = case.db.execute(
            "INSERT INTO events(name,slug,short_name) VALUES('原页面报名练习','host-browser-open','HBO')"
        ).lastrowid
        case.db.commit()
        assert (
            case.post(
                case.admin,
                f"/admin/events/{open_id}/registration-control/enable",
                json={"registration_deadline": case.deadline},
            ).status_code
            == 200
        )
        players = {}
        for device, account in zip(("desktop", "mobile"), case.accounts[:2], strict=True):
            session_cookie = case.client(user_id=account).get_cookie(
                app.config["SESSION_COOKIE_NAME"]
            )
            assert session_cookie is not None
            players[device] = {"name": session_cookie.key, "value": session_cookie.value}
        with make_server("127.0.0.1", 0, app, threaded=True, request_handler=Quiet) as server:
            serving = Thread(target=server.serve_forever)
            serving.start()
            try:
                output = Path(sys.argv[2])
                output.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ["node", str(Path(sys.argv[1]) / "browser_review.cjs")],
                    input=json.dumps(
                        {
                            "base": f"http://127.0.0.1:{server.server_port}",
                            "event": case.event_url,
                            "match": f"/matches/{mid}",
                            "bp": f"/bp/{mid}",
                            "admin_match": f"/admin/matches/edit/{mid}",
                            "team": display["team1"]["name"],
                            "cookie": {"name": cookie.key, "value": cookie.value},
                            "signup": "/events/host-browser-open",
                            "players": players,
                            "output": str(output),
                        }
                    ),
                    text=True,
                    timeout=120,
                    check=False,
                )
                if result.returncode == 0:
                    assert (
                        case.db.execute(
                            "SELECT count(*) FROM event_signup_entries WHERE event_id=?", (open_id,)
                        ).fetchone()[0]
                        == 2
                    )
                    assert (
                        case.db.execute(
                            "SELECT count(*) FROM event_individual_registrations WHERE event_id=?",
                            (open_id,),
                        ).fetchone()[0]
                        == 0
                    )
                return result.returncode
            finally:
                server.shutdown()
                serving.join()
    finally:
        case.doCleanups()


if __name__ == "__main__":
    raise SystemExit(main())
