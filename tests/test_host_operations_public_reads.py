"""访客从原直播 API、战报和赛事页读取隔离宿主库。"""

import json
from unittest.mock import patch

import pytest
from flask import template_rendered

from app import app
from services.live_log_service import persist_live_match_events
from site_core.host import HostError, write
from site_core.matches import live, operations, participants, results
from tests import test_host_operations_live as live_fixtures
from tests import test_host_operations_results as result_fixtures
from tests import test_host_operations_stats as stats_fixtures
from utils import poster


def page(visitor, path):
    contexts = []

    def capture(sender, template, context, **extra):
        contexts.append(context)

    with template_rendered.connected_to(capture, app):
        response = visitor.get(path, follow_redirects=True)
    assert response.status_code == 200
    return response.get_data(as_text=True), contexts[-1]


@pytest.fixture
def game():
    case = live_fixtures.HostLiveOperationsTests()
    try:
        case.setUp()
        yield case
    finally:
        case.doCleanups()


def test_public_live_and_report_select_attempt_even_without_volatile_frame(game):
    g = game
    g.authorize()
    data = g.gsi()
    ct = next(p for p, row in data["allplayers"].items() if row["team"] == "CT")
    t = next(p for p, row in data["allplayers"].items() if row["team"] == "T")
    data["_80gotv"]["round_events"] = [{"round_number": 1, "winner_side": "CT"}]
    data["_80gotv"]["death_markers"] = [
        {
            "id": "original-death",
            "round_number": 2,
            "steamid": ct,
            "side": "CT",
            "name": "Original victim",
            "x": 0,
            "y": 0,
            "z": 0,
        }
    ]
    data["bomb"] = {"state": "planted", "site": "A", "player": t}
    original = g.live(data)["map_run_id"]
    live_url, report = f"/api/live/{g.match_id}", f"/matches/{g.match_id}/report"
    frame = g.client.get(live_url).json
    assert frame["round_history"][0]["winner"] == "t1"
    assert frame["death_markers"] == frame["kill_markers"]
    assert frame["death_markers"][0]["steamid"] == ct and not frame["kill_events"]
    assert frame["bomb_events"][0]["round"] == 2
    stale = g.db.execute(
        "SELECT live_state FROM live_match_data WHERE match_id=?", (g.match_id,)
    ).fetchone()[0]
    assert g.result(g.final())["applied"]
    with write(g.db):
        results.settle_series(g.db, g.match_id, actor=g.chain.admin_id)
        g.db.execute("DELETE FROM live_match_data WHERE match_id=?", (g.match_id,))
    archived = g.client.get(live_url).json
    assert archived["ok"] and not archived["has_gsi"]
    assert archived["map_run_id"] == original and archived["team1"]["score"] == 13
    html, context = page(g.client, report)
    assert [e["type"] for e in context["timeline"]] == ["round", "death", "plant"]
    assert "Original victim" in html and "planted the bomb" in html
    with write(g.db):
        operations.technical_replay(
            g.db, g.match_id, original, admin_id=g.chain.admin_id, reason="测试重打"
        )
        # Simulate a retained frame; read selection must not depend on cache cleanup.
        live.save_snapshot(g.db, g.match_id, json.loads(stale))
    void = g.client.get(live_url).json
    assert not void["ok"] and void["reason"] == "map_run_void"
    assert not void["death_markers"] and not void["round_history"]
    assert not page(g.client, report)[1]["timeline"]

    with write(g.db):
        replay = operations.observe_start(
            g.db,
            g.match_id,
            g.scheduled_id,
            source=f"admin:{g.chain.admin_id}",
            evidence="实际重开",
            previous_map_run_id=original,
        )
        live.bind_director_session(
            g.db, g.match_id, replay, g.fresh_session, actor=g.chain.admin_id, reason="核对新会话"
        )
        g.db.execute("DELETE FROM live_match_data WHERE match_id=?", (g.match_id,))
    assert g.live(g.gsi(session=g.fresh_session, score=(0, 1)))["map_run_id"] == replay
    with write(g.db):
        live.save_snapshot(g.db, g.match_id, json.loads(stale))
    frame = g.client.get(live_url).json
    assert frame["map_run_id"] == replay and not frame["bomb_events"] and not frame["kill_markers"]
    assert [(r["round"], r["winner"]) for r in frame["round_history"]] == [(1, "t2")]
    assert "Original victim" not in page(g.client, report)[0]
    with write(g.db):
        g.db.execute("DELETE FROM live_match_data WHERE match_id=?", (g.match_id,))
    overtime = g.gsi(session=g.fresh_session, seq=1794960050001, round_number=25, score=(13, 12))
    overtime["_80gotv"]["round_events"] = [{"round_number": 25, "winner_side": "CT"}]
    g.live(overtime)
    frame = g.client.get(live_url).json
    assert [r["round"] for r in frame["round_history"]] == [1]
    assert [r["round"] for r in frame["overtime_history"]] == [25]
    assert frame["latest_round_result"]["round"] == 25


def test_legacy_live_history_and_bracket_still_render(game):
    g = game
    with write(g.db):
        bracket = {
            "tournament": {
                "rounds": [
                    {
                        "name": "历史轮次",
                        "matches": [
                            {
                                "id": "old",
                                "team1": "Old home",
                                "team2": "Old away",
                                "score1": 1,
                                "score2": 0,
                            }
                        ],
                    }
                ]
            }
        }
        eid = g.db.execute(
            "INSERT INTO events(name,bracket_data) VALUES(?,?)", ("旧赛事", json.dumps(bracket))
        ).lastrowid
        mid = g.db.execute(
            "INSERT INTO matches(event_id,status) VALUES(?,'completed')", (eid,)
        ).lastrowid
        state = {
            "gotv": {"map_name": "de_nuke"},
            "kill_events": [
                {"id": "legacy", "round": 1, "map_name": "de_nuke", "victim": "Legacy victim"}
            ],
        }
        persist_live_match_events(g.db, mid, state)
        live.save_snapshot(g.db, mid, state)
    assert g.client.get(f"/api/live/{mid}").json["kill_events"][0]["victim"] == "Legacy victim"
    assert "Legacy victim" in page(g.client, f"/matches/{mid}/report")[0]
    assert "Old away" in page(g.client, f"/events/{eid}")[0]
    assert not g.client.get("/api/live/999999").json["ok"]


def test_public_bracket_reads_only_configured_matches_and_current_settlement():
    g = result_fixtures.SettlementTests()
    try:
        g.setUp()
        g.schedule("BO1")
        visitor = app.test_client()
        url = f"/events/{g.eid}"
        assert "event-bracket-panel" not in page(visitor, url)[0]
        with write(g.db):
            target = g.next_match(both=True)
            g.db.execute("INSERT INTO matches(event_id,stage) VALUES(?,'不在签表')", (g.eid,))

        def cards():
            html, context = page(visitor, url)
            data = json.loads(context["event"]["bracket_data"])["tournament"]
            nodes = [m for r in data["rounds"] for m in r["matches"]]
            assert [n["match_id"] for n in nodes] == [g.mid, target]
            assert html.count('class="bracket-card"') == 2
            assert f'href="/matches/{target}" class="bmp-match-link"' in html
            assert not g.db.execute(
                "SELECT bracket_data FROM events WHERE id=?", (g.eid,)
            ).fetchone()[0]
            return nodes

        first, final = cards()
        assert first["team1"] != first["team2"] and first["score1"] is None
        assert final["team1"] is None and final["team1_source"] == {"winner": first["id"]}
        assert final["team2"] is None and final["team2_source"] == {"loser": first["id"]}
        with write(g.db):
            operations.authorize(g.db, g.mid, result_fixtures.ORGANIZER_ID)
            run = g.play(0)
        assert cards()[1]["team1"] is None  # 图已裁定、系列未结算
        with write(g.db):
            g.settle()
        first, final = cards()
        assert (final["team1"], final["team2"]) == (first["team1"], first["team2"])
        with write(g.db):
            g.correct(run, 7, 13)
        first, final = cards()
        assert (first["score1"], first["score2"]) == (0, 1)
        assert first["maps"] == [{"name": "Mirage", "t1": 7, "t2": 13}]
        assert (final["team1"], final["team2"]) == (first["team2"], first["team1"])
        with write(g.db):
            results.reopen_series(
                g.db, g.mid, actor=result_fixtures.ORGANIZER_ID, reason="核对赛果"
            )
        final = cards()[1]
        assert final["team1"] is None and final["team2"] is None
    finally:
        g.doCleanups()


def test_only_detached_link_keeps_both_cards_and_actual_opponents():
    g = result_fixtures.SettlementTests()
    try:
        g.setUp()
        g.schedule("BO1")
        admin = result_fixtures.ORGANIZER_ID
        with write(g.db):
            target = g.next_match()
            sides = dict(
                g.db.execute(
                    "SELECT side_key,event_entrant_id FROM match_participants WHERE match_id=?",
                    (g.mid,),
                )
            )
            g.db.execute(
                "INSERT INTO match_participants(match_id,event_id,side_key,event_entrant_id) VALUES(?,?,'away',?)",
                (target, g.eid, sides["away"]),
            )
            operations.authorize(g.db, g.mid, admin)
            run = g.play(0)
            state = g.settle()
            participants.freeze_rosters(g.db, target, admin)
        with pytest.raises(HostError), write(g.db):
            g.correct(run, 7, 13)
        with write(g.db):
            results.confirm_map(
                g.db,
                g.mid,
                g.slots[0],
                run,
                7,
                13,
                actor=admin,
                source="admin",
                reason="已核对下游冻结名单，保留原对手",
                expected_revision=state["maps"][0]["revision"],
                expected_series_revision=state["revision"],
                retain_downstream=[
                    {
                        "target_match_id": target,
                        "target_side": "home",
                        "retained_entrant_id": sides["home"],
                        "proposed_entrant_id": sides["away"],
                    }
                ],
            )
        html, ctx = page(app.test_client(), f"/events/{g.eid}")
        rounds = json.loads(ctx["event"]["bracket_data"])["tournament"]["rounds"]
        source, kept = [m for stage in rounds for m in stage["matches"]]
        assert html.count('class="bracket-card"') == 2 and kept["match_id"] == target
        assert (source["score1"], source["score2"]) == (0, 1)
        assert kept["team1"] == source["team1"] and kept["team2"] == source["team2"]
        assert kept["team1"] != kept["team2"] and "team1_source" not in kept
    finally:
        g.doCleanups()


def test_report_and_poster_read_official_slots_and_partial_metrics():
    g = stats_fixtures.HostOperationsStatsTests()
    try:
        g.setUp()
        runs = []
        with write(g.db):
            for slot, (fields, score) in enumerate(
                [
                    ({"rounds": 18}, (13, 5)),
                    ({"rounds": 20, "kills": 12, "damage": 1200}, (7, 13)),
                    ({}, (13, 10)),
                ]
            ):
                run = g._start(slot)
                runs.append(run)
                g._record(run, g.player)
                if fields:
                    g._apply(run, g.player, "all", fields)
                if slot < 2:
                    g.db.execute(
                        """INSERT INTO live_run_events(map_run_id,event_type,event_key,round_number,payload)
                           VALUES(?,'round','1',1,'{"side":"ct","map_name":"de_mirage"}')""",
                        (run,),
                    )
                g._confirm(slot, run, *score)
        url = f"/matches/{g.match}/report"
        html, report = page(g.visitor, url)
        stats = report["team_stats"]
        assert (stats["t1_k"], stats["t1_adr"], stats["t1_d"]) == (12, 60, None)
        assert report["mvp"] is None and "MATCH MVP" not in html
        assert [m["t1_best"]["kills"] for m in report["map_reports"]] == [None, 12, None]
        assert [e["scheduled_map_id"] for e in report["timeline"]] == g.scheduled[:2]
        assert "图1 · Mirage · R1" in html and "图2 · Mirage · R1" in html

        with write(g.db):
            for run, rating in zip(runs, (1, 2, 9)):
                g._apply(run, g.player, "all", {"rating": rating})
        _, report = page(g.visitor, url)
        assert (report["mvp"]["kills"], report["mvp"]["adr"], report["mvp"]["rating"]) == (
            12,
            60,
            1.53,
        )
        with patch(
            "utils.poster.generate_match_poster", wraps=poster.generate_match_poster
        ) as draw:
            png = g.visitor.get(f"/matches/{g.match}/poster", follow_redirects=True)
        assert (
            png.status_code == 200
            and png.mimetype == "image/png"
            and png.data.startswith(b"\x89PNG")
        )
        ratings = draw.call_args.args[2]
        assert len(ratings) == 1 and ratings[0]["rating"] == pytest.approx(58 / 38)
    finally:
        g.doCleanups()
