"""在隔离的测试站点验收报名、阶段、出场和荣誉操作。"""

import sys
from datetime import date, timedelta
from pathlib import Path

ENTRY = Path(__file__).resolve()
ROOT = ENTRY.parents[3]
sys.path.insert(0, str(ENTRY.parent.parent / "slice-03-match-operations"))
import frontend_slice3_audit as audit  # noqa: E402


def prepare():
    from app import app
    from site_core.host import write
    from tests.test_host_prematch_chain import HostPrematchChainTests

    case = HostPrematchChainTests()
    case.setUp()
    try:
        mid = case.prepare_through_host()
        with write(case.db):
            case.db.execute("UPDATE matches SET stage='总决赛' WHERE id=?", (mid,))
            clubs = [case.db.execute("INSERT INTO teams(name,short_name) VALUES(?,?)", (name, name)).lastrowid
                     for name in ("Atlas", "Relay")]

        case.assertEqual(case.post(case.admin, "/admin/events/add", data={
            "name": "Campus Open", "short_name": "OPEN",
            "start_date": (date.today() + timedelta(days=1)).isoformat(),
            "end_date": (date.today() + timedelta(days=3)).isoformat(),
            "registration_deadline": str(case.deadline),
        }).status_code, 302)
        signup = case.db.execute("SELECT id FROM events WHERE short_name='OPEN'").fetchone()[0]
        for account, name in zip(case.accounts, ("Northside", "Southside")):
            case.assertEqual(case.post(case.client(user_id=account), f"/events/{signup}/register",
                                       data={"my_slot": 0, "team_name": name}).status_code, 302)

        base = f"/admin/matches/{mid}/operations"

        def post(action, **payload):
            response = case.post(case.admin, f"{base}/{action}", json=payload)
            case.assertTrue(response.get_json()["ok"], response.get_json())
            return response.get_json()

        post("authorize")
        context = case.admin.get(base + "/panel-context").get_json()
        map_id = context["overview"]["maps"][0]["scheduled_map_id"]
        run = post("start", scheduled_map_id=map_id, evidence="本地验收：已实际开打")["map_run_id"]
        home, away = context["context"]["participants"]
        for party in (home, away):
            record = post("participation", map_run_id=run, player_id=party["players"][0]["id"],
                          match_participant_id=party["match_participant_id"], reason="现场登记")
        post("review-participation", participation_id=record["participation_id"], present=False,
             expected_revision=1, reason="本局实际未上场")
        case.admin.get("/admin/matches")
        cookie = case.admin.get_cookie(app.config["SESSION_COOKIE_NAME"])
        return case, app, cookie, {
            "eid": case.event_id, "signup": signup, "clubs": clubs, "mid": mid, "run": run, "map": map_id,
            "home": [p["id"] for p in home["players"]], "away": [p["id"] for p in away["players"]],
        }
    except Exception:
        case.doCleanups()
        raise


if __name__ == "__main__":
    if "--child" in sys.argv:
        raise SystemExit(audit.serve(ROOT, seed_data=prepare, driver=ENTRY.with_suffix(".cjs"),
                                     output_name="frontend-refinement"))
    raise SystemExit(audit.isolated_run(ROOT, ENTRY))
