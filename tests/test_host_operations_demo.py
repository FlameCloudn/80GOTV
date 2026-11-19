import io
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import app as site_app
from config import Config
from models import get_db, init_tables
from routes import matches as match_routes
from site_core.events import public, registration
from site_core.host import write
from site_core.matches import (
    demo_analysis,
    demo_storage,
    maps,
    operations,
    participants,
    results,
    statistics,
)
from tests.entrant_slice_fixtures import DEADLINE, ORGANIZER_ID, REGISTRATION_TIME, seed_registrants

DEMO = b"PBDEMS2\x00" + b"local demo test bytes"
CSRF = {"X-CSRF-Token": "host-demo-fixture"}


@pytest.fixture
def hosted_demo(tmp_path, monkeypatch):
    root = tmp_path / "private"
    monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "host.sqlite"))
    monkeypatch.setattr(Config, "DEFAULT_ADMIN_PASSWORD", "")
    monkeypatch.setitem(site_app.config, "HOST_DEMO_ROOT", str(root))
    init_tables()
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO admins(id,username,password_hash) VALUES(?, 'demo-organizer', 'fixture-disabled')",
            (ORGANIZER_ID,),
        )
        people = seed_registrants(conn, [360] * 11)
        conn.execute("UPDATE users SET is_bashizhong_student=0")
        conn.commit()
        with write(conn):
            event_id = conn.execute("INSERT INTO events(name) VALUES('Demo Cup')").lastrowid
            registration.enable_event(
                conn, event_id, DEADLINE, admin_id=ORGANIZER_ID, now=REGISTRATION_TIME
            )
            groups = []
            for name, team in (("Home", people[:5]), ("Away", people[5:10])):
                group = registration.create_group(
                    conn, event_id, team[0].account_id, name, now=REGISTRATION_TIME
                )
                groups.append(group)
                for slot, person in enumerate(team[1:], 1):
                    registration.join_group(
                        conn, event_id, group, person.account_id, slot, now=REGISTRATION_TIME
                    )
            registration.enroll(
                conn, event_id, people[10].account_id, "independent_reserve", now=REGISTRATION_TIME
            )
            batch = public.form_due_event(conn, event_id, now=DEADLINE)
            entrants = dict(
                conn.execute("SELECT registration_id,event_entrant_id FROM event_entrants")
            )
            home, away = (entrants[group] for group in groups)
            batch = public.confirm_initial_rosters(
                conn,
                event_id,
                [home, away],
                expected_revision=batch["formation_revision"],
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 1,
            )
            public.assign_reserve(
                conn,
                event_id,
                home,
                people[10].player_id,
                expected_revision=batch["formation_revision"],
                admin_id=ORGANIZER_ID,
                now=DEADLINE + 2,
                reason="fixture reserve approval",
            )
            match_id = conn.execute(
                """INSERT INTO matches(event_id,status,bo_format,match_time,slug)
                   VALUES(?,'upcoming','BO3','2027-01-16 13:00:00','host-demo-cup')""",
                (event_id,),
            ).lastrowid
            conn.execute(
                "INSERT INTO match_slug_aliases(slug,match_id) VALUES('old-demo-cup',?)",
                (match_id,),
            )
            participants.bind(conn, match_id, home, away)
            maps.sync_scheduled_maps(
                conn, match_id, setup={"map1": "Mirage", "map2": "Nuke", "map3": "Ancient"}
            )
            participants.freeze_rosters(conn, match_id, ORGANIZER_ID)
            conn.execute(
                "UPDATE matches SET bp_state=? WHERE id=?", ('{"status":"completed"}', match_id)
            )
            operations.authorize(conn, match_id, ORGANIZER_ID)
            map_ids = [row["scheduled_map_id"] for row in maps.list_scheduled_maps(conn, match_id)]
            run_id = operations.observe_start(
                conn, match_id, map_ids[0], source="director", evidence="fixture-start-1"
            )
            match_sides = dict(
                conn.execute("SELECT side_key,match_participant_id FROM match_participants")
            )

    client = site_app.test_client()
    with client.session_transaction() as session:
        session.update(admin_id=ORGANIZER_ID, csrf_token=CSRF["X-CSRF-Token"])
    reader = site_app.test_client()
    with reader.session_transaction() as session:
        session["user_id"] = people[0].account_id
    # Stub only the external CSDA program for synthetic files.
    monkeypatch.setattr(demo_analysis, "find_csda", lambda: sys.executable)
    return SimpleNamespace(
        match_id=match_id,
        map_ids=map_ids,
        run_id=run_id,
        people=people,
        sides=match_sides,
        client=client,
        stranger=site_app.test_client(),
        reader=reader,
        root=root,
        path=f"/admin/matches/{match_id}/api/demos",
    )


def _confirm(game, map_index=0, run_id=None):
    with closing(get_db()) as conn, write(conn):
        return results.confirm_map(
            conn,
            game.match_id,
            game.map_ids[map_index],
            run_id or game.run_id,
            0,
            13,
            actor=ORGANIZER_ID,
            source="admin",
        )


def _upload(
    game, contents=DEMO, *, headers=CSRF, filename="../../Fixture.dem", run_id=None, map_index=0
):
    return game.client.post(
        game.path,
        headers=headers,
        data={
            "demo": (io.BytesIO(contents), filename),
            "scheduled_map_id": game.map_ids[map_index],
            "map_run_id": run_id or game.run_id,
        },
    )


def _payload(people, *, map_name="de_mirage"):
    home, away, absent = people[0], people[5], people[1]
    rounds = [
        {"number": number, "teamASide": a, "teamBSide": 5 - a, "winnerSide": a}
        for number, a in enumerate([3] * 12 + [2], 1)
    ]
    return {
        "mapName": map_name,
        "teamA": {"name": "Away demo", "score": 13},
        "teamB": {"name": "Home demo", "score": 0},
        "rounds": rounds,
        "players": {
            home.steam_id: {
                "name": "Home actual",
                "team": {"letter": "B"},
                "killCount": 0,
                "healthDamage": 0,
                "averageDamagePerRound": 0,
                "assistCount": 0,
            },
            away.steam_id: {"name": "Away actual", "team": {"letter": "A"}, "killCount": 0},
            absent.steam_id: {"name": "Unproved", "team": {"letter": "B"}, "killCount": 0},
        },
        "playerEconomies": [
            {"steamId": person.steam_id, "roundNumber": row["number"], "playerSide": row[side]}
            for row in rounds
            for person, side in ((home, "teamBSide"), (away, "teamASide"))
        ],
        "kills": [],
        "damages": [],
    }


def _parse(game, response):
    assert response.status_code in (200, 201), response.get_json()
    demo_id = response.get_json()["original"]["demo_id"]
    job = game.client.post(f"{game.path}/{demo_id}/parse", headers=CSRF)
    assert job.status_code == 201, job.get_json()
    return _preview(game, job.get_json()["analysis_id"])


def _preview(game, analysis_id):
    response = game.client.get(f"{game.path}/analyses/{analysis_id}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()["analysis"]


def _approval(view, person=None, *, fields=None, record=False, download=False):
    approval = {
        "analysis_id": view["analysis_id"],
        "mapping": view["mapping"],
        "result_revision": view["official_result"]["revision"] if view["official_result"] else None,
        "stats_revision": view["stats_revision"],
        "reason": "verified recording",
        "download_default": download,
    }
    if person:
        approval["players"] = {
            person.steam_id: {
                "player_id": person.player_id,
                "record": record,
                "fields": fields or {},
                "participation_revision": view["players"][person.steam_id][
                    "participation_revision"
                ],
            }
        }
    return approval


def _adopt(game, *approvals):
    return game.client.post(f"{game.path}/adopt", json={"approvals": approvals}, headers=CSRF)


def test_private_receipt_review_and_old_download(hosted_demo, monkeypatch):
    game = hosted_demo
    assert game.stranger.get(game.path).status_code == 401
    assert _upload(game, headers={}).status_code == 403
    assert _upload(game, filename="fixture.zip").status_code == 400
    assert _upload(game, b"not a demo").status_code == 400
    assert _upload(game, map_index=1).status_code == 409
    assert not game.root.exists()
    result = _confirm(game)
    received = _upload(game)
    assert received.status_code == 201
    original = received.get_json()["original"]
    assert {"storage_key", "filename"}.isdisjoint(original)
    duplicate = _upload(game, filename="Another.DEM")
    assert duplicate.status_code == 200
    assert duplicate.get_json()["original"]["demo_id"] == original["demo_id"]
    assert len(list(game.root.glob("*.dem"))) == 1

    monkeypatch.setattr(
        demo_analysis, "run_analysis", lambda *_args, **_kwargs: _payload(game.people)
    )
    view = _parse(game, received)
    assert view["mapping"] == {"A": game.sides["away"], "B": game.sides["home"]}
    assert view["candidate_score"] == {"score1": 0, "score2": 13}
    assert view["official_result"]["revision"] == result["revision"]
    assert not view["blocks"]
    assert not view["players"][game.people[1].steam_id]["rounds"]
    assert "damage" not in view["players"][game.people[5].steam_id]["fields"]["all"]

    download_url = "/matches/host-demo-cup/download-demo?slot=0"
    assert site_app.test_client().get(download_url).status_code == 302
    assert game.reader.get(download_url).status_code == 404
    admin_file = f"{game.path}/{original['demo_id']}/file"
    assert game.stranger.get(admin_file).status_code == 401
    with game.client.get(admin_file) as response:
        assert response.data == DEMO

    actor = game.people[0]
    selected = _approval(
        view,
        actor,
        record=True,
        download=True,
        fields={
            "all": {"kills": "accept", "damage": "accept", "rounds_played": "accept"},
            "ct": {"rounds_played": "accept", "kills": "accept"},
        },
    )
    bad_mapping = {**selected, "mapping": {"A": game.sides["home"], "B": game.sides["away"]}}
    assert _adopt(game, bad_mapping).status_code == 409
    bad_field = _approval(view, actor, record=True, fields={"all": {"deaths": "accept"}})
    assert _adopt(game, bad_field).status_code == 400
    with closing(get_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM run_participations").fetchone()[0] == 0

    applied = _adopt(game, selected)
    assert applied.status_code == 200, applied.get_json()
    assert _adopt(game, selected).get_json()["adoptions"][0]["duplicate"]
    newer = _parse(game, duplicate)
    next_selection = _approval(
        newer, actor, record=True, fields=selected["players"][actor.steam_id]["fields"]
    )
    assert _adopt(game, next_selection).status_code == 200
    with closing(get_db()) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM run_participations WHERE is_current=1").fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM run_round_participations").fetchone()[0] == 13
        assert conn.execute("SELECT COUNT(*) FROM official_player_map_stats").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM run_stats_revisions").fetchone()[0] == 2
        assert (
            dict(
                conn.execute(
                    "SELECT map_run_id,score1,score2,revision FROM official_map_results"
                ).fetchone()
            )
            == view["official_result"]
        )
        assert statistics.read_fields(conn, game.run_id, actor.player_id, "all")["fields"] == {
            "kills": 0,
            "damage": 0,
            "rounds_played": 13,
        }
    alias = game.reader.get("/matches/old-demo-cup/download-demo?slot=0")
    assert alias.status_code == 301 and alias.location == download_url
    with game.reader.get(download_url) as response:
        assert response.status_code == 200 and response.data == DEMO
        assert "attachment" in response.headers["Content-Disposition"]
    assert game.reader.get("/matches/host-demo-cup/download-demo?slot=1").status_code == 404


def test_public_match_links_only_to_readable_default_demo_slots(hosted_demo, monkeypatch, caplog):
    game = hosted_demo
    _confirm(game)
    with closing(get_db()) as conn, write(conn):
        run2 = operations.observe_start(
            conn, game.match_id, game.map_ids[1], source="director", evidence="fixture-second-map"
        )
    _confirm(game, map_index=1, run_id=run2)
    monkeypatch.setattr(
        demo_analysis,
        "run_analysis",
        lambda *_args, **_kwargs: _payload(game.people, map_name="de_nuke"),
    )
    contents = DEMO + b"approved second map"
    view = _parse(game, _upload(game, contents, map_index=1, run_id=run2))
    page = "/matches/host-demo-cup"
    target = page + "/download-demo?slot=1"
    missing_slot = page + "/download-demo?slot=0"
    statements = []
    connect = match_routes.get_db

    def trace_match_queries():
        conn = connect()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(match_routes, "get_db", trace_match_queries)
    with game.stranger.get(page) as response:
        assert response.status_code == 200
        assert 'class="list-row mh-watch-row is-demo"' not in response.get_data(as_text=True)
    assert sum("demo_adoptions" in sql for sql in statements) == 1
    assert game.reader.get(target).status_code == 404

    approval = _adopt(game, _approval(view, download=True))
    assert approval.status_code == 200, approval.get_json()
    latest_contents = DEMO + b"latest default"
    latest = _parse(game, _upload(game, latest_contents, map_index=1, run_id=run2))
    assert _adopt(game, _approval(latest, download=True)).status_code == 200
    with closing(get_db()) as conn:
        keys = dict(conn.execute("SELECT demo_id,storage_key FROM demo_originals"))
    key = keys[latest["demo_id"]]
    statements.clear()
    with game.stranger.get(page) as response:
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert f'href="{target}"' in html
        assert f'href="{missing_slot}"' not in html
        assert all(key not in html for key in keys.values())
    assert sum("demo_adoptions" in sql for sql in statements) == 1
    with game.reader.get(target, headers={"Range": f"bytes={len(DEMO)}-"}) as response:
        assert response.status_code == 206 and response.data == b"latest default"
    assert game.reader.get(missing_slot).status_code == 404

    selected_file = game.root / key
    lstat = Path.lstat

    def deny_selected_file(path, *args, **kwargs):
        if path == selected_file:
            raise PermissionError(13, "fixture permission denied", str(path))
        return lstat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", deny_selected_file)
        with game.stranger.get(page) as response:
            assert response.status_code == 200 and f'href="{target}"' not in response.get_data(
                as_text=True
            )
        with game.reader.get(target) as response:
            assert response.status_code == 503 and str(selected_file) not in response.get_data(
                as_text=True
            )
    assert "托管 Demo 可读性检查失败" in caplog.text and "托管 Demo 下载失败" in caplog.text
    assert key not in caplog.text

    caplog.clear()
    with monkeypatch.context() as patch:
        patch.setitem(site_app.config, "HOST_DEMO_ROOT", site_app.static_folder)
        with game.stranger.get(page) as response:
            assert response.status_code == 200 and f'href="{target}"' not in response.get_data(
                as_text=True
            )
        assert game.reader.get(target).status_code == 503
    assert "托管 Demo 下载目录不可用" in caplog.text

    monkeypatch.setattr(
        demo_analysis, "run_analysis", lambda *_args, **_kwargs: _payload(game.people)
    )
    other_slot = _parse(game, _upload(game, DEMO + b"other slot"))
    assert _adopt(game, _approval(other_slot, download=True)).status_code == 200
    selected_file.rename(game.root / "fixture-missing.dem")
    caplog.clear()
    with game.stranger.get(page) as response:
        html = response.get_data(as_text=True)
        assert response.status_code == 200 and f'href="{target}"' not in html
        assert f'href="{missing_slot}"' in html
    assert (game.root / keys[view["demo_id"]]).is_file()
    assert game.reader.get(target).status_code == 404
    assert "托管 Demo" not in caplog.text
    with closing(get_db()) as conn:
        assert (
            conn.execute("SELECT demo_file FROM matches WHERE id=?", (game.match_id,)).fetchone()[0]
            is None
        )


def test_reparse_failure_stays_visible_and_runs_without_writer_lock(hosted_demo, monkeypatch):
    game = hosted_demo
    receipt = _upload(game)

    def analyze(*_args, **_kwargs):
        with closing(get_db()) as other, write(other):
            assert (
                other.execute(
                    "SELECT status FROM demo_analyses ORDER BY analysis_id DESC LIMIT 1"
                ).fetchone()[0]
                == "running"
            )
        return _payload(game.people)

    monkeypatch.setattr(demo_analysis, "run_analysis", analyze)
    ready = _parse(game, receipt)

    def fail(*_args, **_kwargs):
        raise RuntimeError("csda 分析超时（超过 300 秒）")

    monkeypatch.setattr(demo_analysis, "run_analysis", fail)
    demo_id = receipt.get_json()["original"]["demo_id"]
    failure = game.client.post(f"{game.path}/{demo_id}/parse", headers=CSRF)
    assert failure.status_code == 422
    failed = _preview(game, failure.get_json()["analysis_id"])
    assert failed["status"] == "failed" and "超时" in failed["error"]
    assert _preview(game, ready["analysis_id"])["status"] == "ready"
    assert len(list(game.root.iterdir())) == 1


def test_registration_failure_preserves_the_received_bytes(hosted_demo):
    game = hosted_demo
    with closing(get_db()) as conn:
        conn.execute("""CREATE TEMP TRIGGER reject_demo BEFORE INSERT ON demo_originals
                        BEGIN SELECT RAISE(ABORT, 'registration failed'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="registration failed"):
            demo_storage.receive_original(
                conn,
                root=game.root,
                match_id=game.match_id,
                scheduled_map_id=game.map_ids[0],
                run_id=game.run_id,
                stream=io.BytesIO(DEMO),
                filename="fixture.dem",
                actor=ORGANIZER_ID,
            )
        assert conn.execute("SELECT COUNT(*) FROM demo_originals").fetchone()[0] == 0
    (unregistered,) = game.root.iterdir()
    assert unregistered.name.startswith(f"run-{game.run_id}-") and unregistered.read_bytes() == DEMO


def test_field_conflict_and_withdrawn_participation_are_not_overwritten(hosted_demo, monkeypatch):
    game = hosted_demo
    _confirm(game)
    home = game.people[0]
    with closing(get_db()) as conn, write(conn):
        pid = operations.record_participation(
            conn,
            game.run_id,
            home.player_id,
            game.sides["home"],
            source="admin",
            actor=ORGANIZER_ID,
        )
        statistics.apply_fields(
            conn,
            game.run_id,
            home.player_id,
            "all",
            {"kills": 7},
            source="admin",
            actor=ORGANIZER_ID,
            reason="manual verification",
            expected=0,
            confirm=True,
        )
    monkeypatch.setattr(
        demo_analysis, "run_analysis", lambda *_args, **_kwargs: _payload(game.people)
    )
    view = _parse(game, _upload(game))
    assert view["players"][home.steam_id]["diffs"]["all"]["conflicts"]["kills"]["before"] == 7
    assert (
        _adopt(game, _approval(view, home, fields={"all": {"kills": "accept"}})).status_code == 409
    )
    fill = _approval(view, home, fields={"all": {"assists": "accept"}})
    assert _adopt(game, fill).status_code == 200
    assert (
        _adopt(game, _approval(view, home, fields={"all": {"kills": "replace"}})).status_code == 409
    )
    current = _preview(game, view["analysis_id"])
    replacement = _approval(current, home, fields={"all": {"kills": "replace"}})
    assert _adopt(game, replacement).status_code == 200
    with closing(get_db()) as conn, write(conn):
        stats = statistics.read_fields(conn, game.run_id, home.player_id, "all")
        assert stats["fields"] == {"kills": 0, "assists": 0}
        assert (
            stats["field_sources"]["kills"]["source_ref"]
            == f"demo:1/analysis:{view['analysis_id']}"
        )
        operations.review_participation(
            conn,
            game.match_id,
            pid,
            present=False,
            expected_revision=1,
            admin_id=ORGANIZER_ID,
            reason="manual withdrawal",
        )
    current = _preview(game, view["analysis_id"])
    assert current["players"][home.steam_id]["withdrawn"]
    refused = _adopt(game, _approval(current, home, record=True))
    assert refused.status_code == 409 and "撤回" in refused.get_json()["error"]
    with closing(get_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM official_player_map_stats").fetchone()[0] == 0


def test_void_original_keeps_its_lineup_and_cannot_attach_to_replay(hosted_demo, monkeypatch):
    game = hosted_demo
    _confirm(game)
    monkeypatch.setattr(
        demo_analysis, "run_analysis", lambda *_args, **_kwargs: _payload(game.people)
    )
    receipt = _upload(game)
    first = _parse(game, receipt)
    assert _adopt(game, _approval(first, download=True)).status_code == 200
    with closing(get_db()) as conn, write(conn):
        operations.technical_replay(
            conn,
            game.match_id,
            game.run_id,
            admin_id=ORGANIZER_ID,
            reason="technical outage",
            outgoing_player_id=game.people[0].player_id,
            incoming_player_id=game.people[10].player_id,
        )
        replay_id = operations.observe_start(
            conn, game.match_id, game.map_ids[0], source="director", evidence="fixture-replay"
        )
    _confirm(game, run_id=replay_id)
    assert game.reader.get("/matches/host-demo-cup/download-demo").status_code == 404
    assert _upload(game, run_id=replay_id).status_code == 409
    old = _parse(game, _upload(game))
    assert (
        old["players"][game.people[0].steam_id]["lineup"]["player_id"] == game.people[0].player_id
    )
    assert any("作废" in item for item in old["blocks"])
    assert _adopt(game, _approval(old, game.people[0], record=True)).status_code == 409
    assert len(list(game.root.iterdir())) == 1


def test_legacy_bridge_requires_run_and_batch_does_not_half_apply(hosted_demo, monkeypatch):
    game = hosted_demo
    _confirm(game)
    bridge = f"/admin/matches/{game.match_id}/import-demo"
    monkeypatch.setattr(
        demo_analysis, "run_analysis", lambda *_args, **_kwargs: _payload(game.people)
    )
    no_run = game.client.post(
        bridge, headers=CSRF, data={"demo_file_0": (io.BytesIO(DEMO), "a.dem")}
    )
    assert no_run.status_code == 400
    bridged = game.client.post(
        bridge,
        headers=CSRF,
        data={
            "demo_file_0": (io.BytesIO(DEMO), "a.dem"),
            "scheduled_map_id": game.map_ids[0],
            "map_run_id": game.run_id,
        },
    )
    assert bridged.status_code == 201, bridged.get_json()
    first = bridged.get_json()["analysis"]
    with closing(get_db()) as conn, write(conn):
        run2 = operations.observe_start(
            conn, game.match_id, game.map_ids[1], source="director", evidence="fixture-start-2"
        )
    _confirm(game, map_index=1, run_id=run2)
    wrong_map = _parse(game, _upload(game, DEMO + b"second", run_id=run2, map_index=1))
    assert any("排定赛图" in block for block in wrong_map["blocks"])
    selected = _approval(first, game.people[0], record=True)
    refused = _adopt(game, selected, _approval(wrong_map, download=True))
    assert refused.status_code == 409
    with closing(get_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM demo_originals").fetchone()[0] == 2
        assert (
            conn.execute("SELECT COUNT(*) FROM run_participations WHERE is_current=1").fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM demo_adoptions").fetchone()[0] == 0
    applied = game.client.post(
        bridge, headers=CSRF, data={"step": "import_single", "approvals": json.dumps([selected])}
    )
    assert applied.status_code == 200, applied.get_json()


@pytest.mark.parametrize("freeze", ["archived", "cancelled"])
def test_closed_event_or_cancelled_match_keeps_original_read_only(hosted_demo, monkeypatch, freeze):
    game = hosted_demo
    _confirm(game)
    monkeypatch.setattr(
        demo_analysis, "run_analysis", lambda *_args, **_kwargs: _payload(game.people)
    )
    view = _parse(game, _upload(game))
    approval = _approval(view, game.people[0], record=True, download=True)
    assert not view["blocks"]
    with closing(get_db()) as conn, write(conn):
        if freeze == "archived":
            conn.execute("UPDATE event_registration_control SET archived_at=CURRENT_TIMESTAMP")
        else:
            conn.execute("UPDATE matches SET status='cancelled' WHERE id=?", (game.match_id,))
    refused = _adopt(game, approval)
    assert refused.status_code == 409 and "不能采纳" in refused.get_json()["error"]
    assert _preview(game, view["analysis_id"])["blocks"]
    newer = _parse(game, _upload(game, DEMO + b"late original"))
    assert newer["status"] == "ready" and newer["blocks"]
    assert game.reader.get("/matches/host-demo-cup/download-demo?slot=0").status_code == 404
    with closing(get_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM demo_originals").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM demo_adoptions").fetchone()[0] == 0
