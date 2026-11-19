"""Replay the synthetic event in a real, loopback-only Chromium browser."""

import json
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from threading import Thread

from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).with_suffix(".cjs")
ARTIFACTS = ROOT / "output/ui-audit/entrant-slice-01"
sys.path.insert(0, str(ROOT))


class QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


def run(workspace: Path):
    from entrant_slice import formation, registration, sample
    from entrant_slice.sandbox import connect, create_app, initialize
    from entrant_slice.storage import write
    from entrant_slice.worker import process_due

    initialize(workspace)
    now = int(time.time())
    duration = 600
    event_id = sample.seed(workspace, now=now, duration=duration)
    with closing(connect(workspace)) as db, write(db):
        admin = db.execute("SELECT id FROM admins WHERE username=?", (sample.ADMIN,)).fetchone()[
            "id"
        ]
        member = db.execute("SELECT id FROM users WHERE username='entrant-demo-12'").fetchone()[
            "id"
        ]
        registration.create_event(
            db, "独立候补练习赛", "reserve-practice", now + 3600, admin_id=admin, now=now
        )
        db.execute(
            "INSERT INTO event_slug_aliases(slug,event_id) VALUES('entrant-practice-old',?)",
            (event_id,),
        )

    app = create_app(workspace)
    client = app.test_client()
    # No password is needed: sign one disposable session for the seeded player.
    with client.session_transaction() as session:
        session["user_id"] = member
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    if cookie is None:
        raise RuntimeError("无法建立一次性合成会话")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietRequestHandler)
    server_thread = Thread(target=server.serve_forever, name="entrant-browser-smoke")
    server_thread.start()

    def browse(stage: str):
        subprocess.run(
            ["node", str(SCRIPT)],
            cwd=ROOT,
            input=json.dumps(
                {
                    "base": f"http://127.0.0.1:{server.server_port}",
                    "stage": stage,
                    "sample": f"/events/{sample.SLUG}",
                    "output": str(ARTIFACTS),
                    "cookie": {"name": cookie.key, "value": cookie.value},
                }
            ),
            encoding="utf-8",
            check=True,
            timeout=45,
        )

    try:
        browse("open")
        cutoff = now + duration + 1
        formed, blocked = process_due(workspace, clock=lambda: cutoff)
        if blocked or len(formed) != 1 or len(formed[0]["entrant_ids"]) != 2:
            raise RuntimeError("合成赛事未在截止办理阶段形成两队")
        batch = formed[0]
        with closing(connect(workspace)) as db, write(db):
            formation.confirm_initial_rosters(
                db,
                event_id,
                batch["entrant_ids"],
                expected_revision=batch["formation_revision"],
                admin_id=admin,
                now=cutoff + 1,
            )
        browse("confirmed")
        with closing(connect(workspace)) as db, write(db):
            registration.archive_event(db, event_id, admin_id=admin, now=cutoff + 2)
        browse("archived")
    finally:
        server.shutdown()
        server_thread.join()
        server.server_close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="80gotv-slice-browser-") as directory:
        run(Path(directory))
    print("本机浏览器与预览服务已关闭，合成数据库已清理。")
