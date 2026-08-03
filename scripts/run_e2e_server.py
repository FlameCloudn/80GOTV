"""Start an isolated local server for browser smoke tests."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="80gotv-e2e-") as temp_dir:
        # Set isolation before importing the app so a local .env can never
        # point browser checks at the real SQLite or Turso database.
        os.environ["FLASK_ENV"] = "testing"
        os.environ["SECRET_KEY"] = "browser-test-secret-not-for-production"
        os.environ["DATABASE_PATH"] = os.path.join(temp_dir, "test.db")
        os.environ["TURSO_URL"] = ""
        os.environ["TURSO_TOKEN"] = ""

        from flask import render_template, session
        from werkzeug.security import generate_password_hash

        from app import app
        from models import get_db, init_tables

        @app.get("/__e2e__/admin-session")
        def _e2e_admin_session():
            session.clear()
            session["admin_id"] = 1
            session["admin_username"] = "e2e-admin"
            return {"ok": True}

        @app.get("/__e2e__/user-session")
        def _e2e_user_session():
            conn = get_db()
            conn.execute(
                """INSERT OR IGNORE INTO users(
                       username, password_hash, group_username,
                       is_placeholder, approval_status
                   ) VALUES(?, ?, ?, 0, 'approved')""",
                ("e2e-user", "not-used-by-browser-tests", "E2E User"),
            )
            user = conn.execute(
                "SELECT id, username FROM users WHERE username=?",
                ("e2e-user",),
            ).fetchone()
            conn.commit()
            conn.close()
            session.clear()
            session["user_id"] = user["id"]
            session["user_username"] = user["username"]
            return {"ok": True, "user_id": user["id"]}

        @app.get("/testing/incomplete-user-session")
        def _e2e_incomplete_user_session():
            conn = get_db()
            conn.execute(
                """INSERT OR IGNORE INTO users(
                       username, password_hash, is_placeholder, approval_status
                   ) VALUES(?, ?, 0, 'approved')""",
                ("e2e-incomplete", "not-used-by-browser-tests"),
            )
            user = conn.execute(
                "SELECT id, username FROM users WHERE username=?",
                ("e2e-incomplete",),
            ).fetchone()
            conn.commit()
            conn.close()
            session.clear()
            session["user_id"] = user["id"]
            session["user_username"] = user["username"]
            session["profile_completion_required"] = True
            return {"ok": True, "user_id": user["id"]}

        @app.get("/profile-completion-preview")
        def _e2e_profile_completion_preview():
            return render_template(
                "base.html",
                session={"user_id": 1, "user_username": "e2e-incomplete"},
                profile_completion_required=True,
                current_user_school_status=None,
                current_user_saved_group_username="",
                csrf_token="browser-preview",
            )

        @app.get("/__e2e__/live-fixture")
        def _e2e_live_fixture():
            conn = get_db()
            event_id = conn.execute(
                """INSERT INTO events(name, short_name, start_date, end_date, status)
                   VALUES('Live UI Browser Test', 'LIVE', '2026-07-01', '2026-08-01', 'ongoing')"""
            ).lastrowid
            team1_id = conn.execute(
                "INSERT INTO teams(name, short_name) VALUES('Team One', 'T1')"
            ).lastrowid
            team2_id = conn.execute(
                "INSERT INTO teams(name, short_name) VALUES('Team Two', 'T2')"
            ).lastrowid
            match_id = conn.execute(
                """INSERT INTO matches(event_id, team1_id, team2_id, match_time, status)
                   VALUES(?, ?, ?, '2026-07-20T20:00', 'live')""",
                (event_id, team1_id, team2_id),
            ).lastrowid
            state = {
                "gsi_received_at": datetime.now(timezone.utc).isoformat(),
                "gsi": {
                    "map": {
                        "name": "de_mirage",
                        "round": 8,
                        "team_ct": {"name": "Team One", "score": 5},
                        "team_t": {"name": "Team Two", "score": 3},
                    },
                    "phase_countdowns": {"phase": "live", "phase_ends_in": "42"},
                    "round": {"phase": "live"},
                    "_80gotv": {"team_ct": "team1", "team_t": "team2"},
                    "allplayers": {
                        "76561198000000001": {
                            "name": "Player One",
                            "team": "CT",
                            "state": {
                                "health": 86,
                                "armor": 100,
                                "helmet": True,
                                "money": 4200,
                            },
                            "match_stats": {"kills": 9, "assists": 2, "deaths": 5, "damage": 740},
                            "weapons": {
                                "weapon_0": {"name": "weapon_ak47", "type": "Rifle"},
                                "weapon_1": {"name": "weapon_glock", "type": "Pistol"},
                            },
                        },
                        "76561198000000002": {
                            "name": "Player Two",
                            "team": "T",
                            "state": {
                                "health": 61,
                                "armor": 70,
                                "helmet": False,
                                "money": 2800,
                            },
                            "match_stats": {"kills": 6, "assists": 1, "deaths": 8, "damage": 510},
                            "weapons": {
                                "weapon_0": {"name": "weapon_ump45", "type": "Submachine Gun"},
                                "weapon_1": {"name": "weapon_usp_silencer", "type": "Pistol"},
                            },
                        },
                    },
                },
                "round_history": [
                    {"round": 0, "winner": "t1", "side": "ct", "reason_code": "elimination"},
                    {"round": 1, "winner": "t2", "side": "t", "reason_code": "bomb_exploded"},
                    {"round": 2, "winner": "t1", "side": "ct", "reason_code": "bomb_defused"},
                    {"round": 3, "winner": "t2", "side": "t", "reason_code": "elimination"},
                    {"round": 4, "winner": "t1", "side": "ct", "reason_code": "time_expired"},
                    {"round": 5, "winner": "t2", "side": "t", "reason_code": "elimination"},
                    {"round": 6, "winner": "t1", "side": "ct", "reason_code": "elimination"},
                    {"round": 7, "winner": "t2", "side": "t", "reason_code": "bomb_exploded"},
                    {"round": 24, "winner": "t1", "side": "ct", "reason_code": "elimination"},
                ],
            }
            conn.execute(
                "INSERT INTO live_match_data(match_id, live_state) VALUES(?, ?)",
                (match_id, json.dumps(state)),
            )
            conn.commit()
            conn.close()
            return {"ok": True, "match_id": match_id}

        @app.get("/__e2e__/live-fixture/<int:match_id>/switch-sides")
        def _e2e_live_fixture_switch_sides(match_id):
            conn = get_db()
            row = conn.execute(
                "SELECT live_state FROM live_match_data WHERE match_id=?",
                (match_id,),
            ).fetchone()
            if not row:
                conn.close()
                return {"ok": False, "error": "fixture not found"}, 404
            state = json.loads(row["live_state"])
            gsi = state["gsi"]
            gsi["map"]["team_ct"] = {"name": "Team Two", "score": 6}
            gsi["map"]["team_t"] = {"name": "Team One", "score": 6}
            gsi["map"]["round"] = 12
            gsi["_80gotv"] = {"team_ct": "team2", "team_t": "team1"}
            gsi["allplayers"]["76561198000000001"]["team"] = "T"
            gsi["allplayers"]["76561198000000002"]["team"] = "CT"
            state["gsi_received_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE live_match_data SET live_state=?, updated_at=CURRENT_TIMESTAMP WHERE match_id=?",
                (json.dumps(state), match_id),
            )
            conn.commit()
            conn.close()
            return {"ok": True, "match_id": match_id}

        app.config.update(TESTING=False, SESSION_COOKIE_SECURE=False)
        init_tables()
        conn = get_db()
        conn.execute(
            """INSERT OR IGNORE INTO users(
                   username, password_hash, is_placeholder, approval_status
               ) VALUES(?, ?, 0, 'approved')""",
            ("e2e-incomplete", generate_password_hash("password123")),
        )
        conn.commit()
        conn.close()
        app.run(host="127.0.0.1", port=5010, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
