import json
import threading
from contextlib import closing

from config import Config
from live_worker import run_background
from models import init_tables
from site_core.database import get_db, write_transaction
from utils import live_poller


def test_local_worker_processes_due_event_without_page_visit(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "worker.db"))
    init_tables()
    with closing(get_db()) as conn, write_transaction(conn):
        admin = conn.execute("SELECT id FROM admins LIMIT 1").fetchone()[0]
        event = conn.execute("INSERT INTO events(name) VALUES('报名截止杯')").lastrowid
        conn.execute(
            "INSERT INTO event_registration_control(event_id,registration_deadline,enabled_by,enabled_at) VALUES(?,1,?,0)",
            (event, admin),
        )
    stop = threading.Event()
    monkeypatch.setattr(stop, "wait", lambda timeout: stop.set())
    run_background(stop)
    with closing(get_db()) as conn:
        assert conn.execute("SELECT event_id FROM event_formation_batches").fetchone()[0] == event
    assert not live_poller._poller_thread.is_alive()


def test_server_poll_releases_database_between_servers_and_keeps_other_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "live.db"))
    init_tables()
    with closing(get_db()) as conn:
        for mid in (1, 2):
            conn.execute(
                """INSERT INTO matches(id, map2, server_address, match_time)
                   VALUES(?,'Mirage','test.invalid:1','2020-01-01')""",
                (mid,),
            )
            conn.execute(
                """INSERT INTO live_match_data(match_id,live_state) VALUES(?, '{"gsi":{"score":7}}')""",
                (mid,),
            )
        conn.commit()

        def sample(_address):
            # 网络查询期间，独立导播连接仍能取得写入权。
            with closing(get_db()) as director:
                director.execute("PRAGMA busy_timeout=0")
                director.execute("BEGIN IMMEDIATE")
                director.rollback()
            return {"online": True, "map_name": "de_mirage"}

        monkeypatch.setattr(live_poller, "query_server", sample)
        live_poller.poll_once(conn)
        for (state,) in conn.execute("SELECT live_state FROM live_match_data ORDER BY match_id"):
            result = json.loads(state)
            assert result["gsi"] == {"score": 7}
            assert result["a2s"]["map_slot"] == 1
            assert result["a2s"]["server"]["online"] is True
