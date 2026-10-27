"""Start an isolated local server for browser smoke tests."""

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="80gotv-e2e-") as temp_dir:
        # Set isolation before importing the app so a local .env can never
        # point browser checks at the real SQLite or Turso database.
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        os.environ["FLASK_ENV"] = "testing"
        os.environ["SECRET_KEY"] = "browser-test-secret-not-for-production"
        os.environ["DATABASE_PATH"] = os.path.join(temp_dir, "test.db")
        os.environ["TURSO_URL"] = ""
        os.environ["TURSO_TOKEN"] = ""

        from flask import render_template, request, send_from_directory, session
        from werkzeug.security import generate_password_hash

        from app import app
        from models import get_db, init_tables
        from utils.db_helpers import remove_uploaded_team_logo, save_uploaded_team_logo

        @app.get("/static/uploads/team_logos/<path:filename>")
        def _e2e_uploaded_team_logo(filename):
            return send_from_directory(
                os.path.join(temp_dir, "static", "uploads", "team_logos"), filename
            )

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
                       is_placeholder, approval_status, is_bashizhong_student
                   ) VALUES(?, ?, ?, 0, 'approved', 0)""",
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

        @app.get("/__e2e__/feedback-records")
        def _e2e_feedback_records():
            conn = get_db()
            try:
                rows = conn.execute(
                    "SELECT * FROM feedback WHERE content=?",
                    (request.args.get("content", ""),),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

        @app.get("/__e2e__/public-backend-fixture")
        def _e2e_public_backend_fixture():
            conn = get_db()
            try:
                team = conn.execute("SELECT id FROM teams WHERE name='E2E Dot Alpha'").fetchone()
                player = conn.execute(
                    "SELECT id FROM players WHERE nickname='E2E Dot Player'"
                ).fetchone()
                other = conn.execute(
                    "SELECT id FROM players WHERE nickname='E2E Compare Other'"
                ).fetchone()
                event = conn.execute("SELECT id FROM events WHERE slug='e2e-dot-cup'").fetchone()
                return {
                    "team_id": team["id"],
                    "player_id": player["id"],
                    "other_player_id": other["id"],
                    "event_id": event["id"],
                }
            finally:
                conn.close()

        @app.get("/__e2e__/review-fixture")
        def _e2e_review_fixture():
            from services.bracket_service import build_event_bracket

            conn = get_db()
            try:
                size = 8 if request.args.get("size") == "8" else 4
                name = "E2E Review " + uuid.uuid4().hex[:10]
                event_id = conn.execute(
                    "INSERT INTO events(name,short_name,start_date,end_date) "
                    "VALUES(?,?,'2027-11-17T10:00','2027-11-18T20:00')",
                    (name, name.replace(" ", "_")),
                ).lastrowid
                teams = []
                for number in range(1, size + 1):
                    name = f"E2E Review {event_id} Team {number}"
                    team_id = conn.execute(
                        "INSERT INTO teams(name,short_name) VALUES(?,?)", (name, f"R{number}")
                    ).lastrowid
                    teams.append({"id": f"t{number}", "db_id": team_id, "name": name})
                if request.args.get("legacy") == "1":
                    data = build_event_bracket(
                        conn,
                        event_id,
                        {
                            "tournament": {
                                "format_key": "4de",
                                "teams": teams,
                                "sections": [
                                    {
                                        "label": "胜者组",
                                        "rounds": [
                                            {
                                                "name": "UB 第一轮",
                                                "matches": [
                                                    {
                                                        "id": "UB_R1_M1",
                                                        "team1": "t1",
                                                        "team2": "t4",
                                                    },
                                                    {
                                                        "id": "UB_R1_M2",
                                                        "team1": "t2",
                                                        "team2": "t3",
                                                    },
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        },
                    )
                    tour = data["tournament"]
                    tour.pop("format_key", None)
                    tour.pop("sections", None)
                    conn.execute(
                        "UPDATE events SET bracket_data=? WHERE id=?", (json.dumps(data), event_id)
                    )
                conn.commit()
                test_match_id = None
                if request.args.get("test_match") == "1":
                    test_match_id = conn.execute(
                        "INSERT INTO matches(event_id,status,is_test_mode,match_time) "
                        "VALUES(?,'upcoming',1,'2027-11-17T14:00')",
                        (event_id,),
                    ).lastrowid
                    conn.commit()
                return {"event_id": event_id, "teams": teams, "test_match_id": test_match_id}
            finally:
                conn.close()

        @app.get("/__e2e__/home-fixture")
        def _e2e_home_fixture():
            conn = get_db()
            try:
                suffix = uuid.uuid4().hex[:8]
                teams = []
                for name, short_name in [("Alpha", "ALP"), ("Bravo", "BRV")]:
                    team_id = conn.execute(
                        "INSERT INTO teams(name,short_name) VALUES(?,?)",
                        (f"E2E Home {name} {suffix}", short_name),
                    ).lastrowid
                    teams.append({"id": team_id, "short_name": short_name})
                event_id = conn.execute(
                    "INSERT INTO events(name,start_date) VALUES(?,?)",
                    (f"E2E Home Cup {suffix}", datetime.now().strftime("%Y-%m-%d")),
                ).lastrowid
                match_id = conn.execute(
                    "INSERT INTO matches(event_id,team1_id,team2_id,status,bo_format,match_time) "
                    "VALUES(?,?,?,'live','BO3',?)",
                    (
                        event_id,
                        teams[0]["id"],
                        teams[1]["id"],
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                ).lastrowid
                featured_news_title = f"E2E Home Cup {suffix} 今晚开打"
                news_ids = []
                for title, publish_time in [
                    ("首页列表检查新闻 " + suffix, "2099-01-01 10:00:00"),
                    (featured_news_title, "2099-01-02 10:00:00"),
                ]:
                    news_ids.append(
                        conn.execute(
                            "INSERT INTO news(title,content,summary,author,publish_time) VALUES(?,?,?,?,?)",
                            (
                                title,
                                "<p>Browser test article.</p>",
                                "本地假数据，仅供页面检查。",
                                "e2e-admin",
                                publish_time,
                            ),
                        ).lastrowid
                    )
                conn.commit()
                return {
                    "match_id": match_id,
                    "teams": teams,
                    "event_id": event_id,
                    "news_ids": news_ids,
                    "featured_news_title": featured_news_title,
                }
            finally:
                conn.close()

        def _dot_match_participants(conn, player_count=1):
            suffix = uuid.uuid4().hex[:8]
            event_id = conn.execute(
                "INSERT INTO events(name) VALUES(?)", (f"E2E Dot Review {suffix}",)
            ).lastrowid
            teams = []
            for side in (1, 2):
                name = f"E2E Dot Side {side} {suffix}"
                team_id = conn.execute(
                    "INSERT INTO teams(name,short_name) VALUES(?,?)", (name, f"D{side}")
                ).lastrowid
                player_ids = []
                for number in range(1, player_count + 1):
                    player_ids.append(
                        conn.execute(
                            "INSERT INTO players(nickname,team_id,steam_id) VALUES(?,?,?)",
                            (
                                f"Dot {suffix} side {side} player {number}",
                                team_id,
                                str(76561198000000000 + team_id * 10 + number),
                            ),
                        ).lastrowid
                    )
                teams.append(
                    {
                        "id": team_id,
                        "name": name,
                        "short_name": f"D{side}",
                        "player_ids": player_ids,
                    }
                )
            return {"event_id": event_id, "teams": teams, "suffix": suffix}

        @app.get("/__e2e__/dot-match-form-fixture")
        def _e2e_dot_match_form_fixture():
            conn = get_db()
            try:
                fixture = _dot_match_participants(conn, player_count=5)
                fixture["match_id"] = conn.execute(
                    """INSERT INTO matches(event_id,team1_id,team2_id,team1_players,team2_players,status,bo_format,match_time,
                       stage,map1,map2,team1_score,team2_score,map1_t1,map1_t2,map2_t1,map2_t2)
                       VALUES(?,?,?,?,?,'upcoming','BO3','2027-11-17T14:00',
                       'E2E Round','de_mirage','de_nuke',0,0,0,0,0,0)""",
                    (
                        fixture["event_id"],
                        fixture["teams"][0]["id"],
                        fixture["teams"][1]["id"],
                        json.dumps(fixture["teams"][0]["player_ids"]),
                        json.dumps(fixture["teams"][1]["player_ids"]),
                    ),
                ).lastrowid
                conn.commit()
                return fixture
            finally:
                conn.close()

        @app.get("/__e2e__/dot-stats-fixture")
        def _e2e_dot_stats_fixture():
            from services.performance_service import refresh_player_performance

            conn = get_db()
            try:
                fixture = _dot_match_participants(conn)
                match_id = conn.execute(
                    """INSERT INTO matches(event_id,team1_id,team2_id,status,bo_format,match_time,
                       map1,map2,team1_score,team2_score,map1_t1,map1_t2,map2_t1,map2_t2)
                       VALUES(?,?,?,'upcoming','BO3','2027-11-17T14:00',
                       'de_mirage','de_nuke',0,0,13,8,0,0)""",
                    (fixture["event_id"], fixture["teams"][0]["id"], fixture["teams"][1]["id"]),
                ).lastrowid
                for map_name in ("de_mirage", "de_nuke"):
                    for side, team in enumerate(fixture["teams"], 1):
                        conn.execute(
                            """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,map_name,
                               kills,deaths,assists,adr,kast,headshot_percentage,impact,rating,rounds_played,
                               data_source,data_status,data_version)
                               VALUES(?,?,?,?,?,10,8,3,70.5,75,50,1.1,1.2,21,'manual_review','final',1)""",
                            (match_id, team["player_ids"][0], team["id"], f"t{side}", map_name),
                        )
                refresh_player_performance(
                    conn, [team["player_ids"][0] for team in fixture["teams"]]
                )
                conn.commit()
                fixture["match_id"] = match_id
                return fixture
            finally:
                conn.close()

        @app.get("/__e2e__/dot-stats-fixture/<int:match_id>/confirm-score")
        def _e2e_dot_stats_confirm_score(match_id):
            conn = get_db()
            try:
                conn.execute("UPDATE matches SET map2_t1=13,map2_t2=8 WHERE id=?", (match_id,))
                conn.commit()
                return {"ok": True}
            finally:
                conn.close()

        @app.get("/__e2e__/dot-match-report-fixture")
        def _e2e_dot_match_report_fixture():
            conn = get_db()
            try:
                fixture = _dot_match_participants(conn)
                match_id = conn.execute(
                    """INSERT INTO matches(event_id,team1_id,team2_id,status,bo_format,match_time,
                       map1,map1_t1,map1_t2,team1_score,team2_score)
                       VALUES(?,?,?,'completed','BO1','2027-11-17T14:00','de_nuke',13,8,1,0)""",
                    (fixture["event_id"], fixture["teams"][0]["id"], fixture["teams"][1]["id"]),
                ).lastrowid
                for side, team in enumerate(fixture["teams"], 1):
                    old_team_id = conn.execute(
                        "INSERT INTO teams(name,short_name) VALUES(?,?)",
                        (f"E2E Former {side} {fixture['suffix']}", f"F{side}"),
                    ).lastrowid
                    conn.execute(
                        """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,map_name,
                           kills,deaths,assists,adr,kast,rating,rounds_played,data_status,data_version)
                           VALUES(?,?,?,?,'de_nuke',?,?,3,?,75,?,21,'final',2)""",
                        (
                            match_id,
                            team["player_ids"][0],
                            old_team_id,
                            f"t{side}",
                            side * 10,
                            side * 5,
                            0 if side == 1 else None,
                            1.5 if side == 1 else 1.2,
                        ),
                    )
                conn.execute(
                    """INSERT INTO match_stats(match_id,player_id,team_id,match_team_side,map_name,
                       kills,deaths,adr,rating,rounds_played,data_status,data_version)
                       VALUES(?,?,?,'t1','de_nuke',999,999,999,9.99,21,'superseded',1)""",
                    (match_id, fixture["teams"][0]["player_ids"][0], fixture["teams"][0]["id"]),
                )
                conn.commit()
                fixture["match_id"] = match_id
                fixture["player_ids"] = [team["player_ids"][0] for team in fixture["teams"]]
                return fixture
            finally:
                conn.close()

        @app.get("/__e2e__/refactor-fixture")
        def _e2e_refactor_fixture():
            from services.performance_service import refresh_player_performance

            conn = get_db()
            try:
                suffix = uuid.uuid4().hex[:8]
                event_id = conn.execute(
                    "INSERT INTO events(name) VALUES(?)", (f"E2E Refactor {suffix}",)
                ).lastrowid
                team1 = conn.execute(
                    "INSERT INTO teams(name,short_name) VALUES(?,?)", (f"E2E Alpha {suffix}", "ALP")
                ).lastrowid
                team2 = conn.execute(
                    "INSERT INTO teams(name,short_name) VALUES(?,?)", (f"E2E Bravo {suffix}", "BRV")
                ).lastrowid
                player_id = conn.execute(
                    "INSERT INTO players(nickname,team_id) VALUES(?,?)",
                    (f"E2E Missing {suffix}", team1),
                ).lastrowid
                match_id = conn.execute(
                    """INSERT INTO matches(event_id,team1_id,team2_id,status,bo_format,
                       team1_score,team2_score,match_time) VALUES(?,?,?,'completed','BO3',2,0,
                       '2098-01-01 12:00:00')""",
                    (event_id, team1, team2),
                ).lastrowid
                conn.execute(
                    """INSERT INTO match_stats(match_id,player_id,team_id,map_name,
                       rounds_played,kills,deaths,rating,adr,headshot_percentage,kast,impact)
                       VALUES(?,?,?,'de_mirage',20,0,0,NULL,NULL,NULL,NULL,NULL)""",
                    (match_id, player_id, team1),
                )
                refresh_player_performance(conn, [player_id])
                conn.commit()
                return {"event_id": event_id, "player_id": player_id, "match_id": match_id}
            finally:
                conn.close()

        @app.get("/__e2e__/review-state/<int:event_id>")
        def _e2e_review_state(event_id):
            conn = get_db()
            try:
                event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                rows = conn.execute(
                    "SELECT * FROM matches WHERE event_id=? ORDER BY id", (event_id,)
                ).fetchall()
                return {"event": dict(event), "matches": [dict(row) for row in rows]}
            finally:
                conn.close()

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
        conn.execute(
            "INSERT INTO admins(username,password_hash) VALUES(?,?)",
            ("e2e-dot-admin", generate_password_hash("e2e-only-admin-password")),
        )
        conn.execute(
            "INSERT INTO admins(username,password_hash) VALUES(?,?)",
            ("e2e-review-admin", generate_password_hash("e2e-only-review-password")),
        )
        first_team = conn.execute(
            "INSERT INTO teams(name,short_name) VALUES('E2E Dot Alpha','EDA')"
        ).lastrowid
        second_team = conn.execute(
            "INSERT INTO teams(name,short_name) VALUES('E2E Dot Beta','EDB')"
        ).lastrowid
        player = conn.execute(
            "INSERT INTO players(nickname,team_id) VALUES('E2E Dot Player',?)", (first_team,)
        ).lastrowid
        other_player = conn.execute(
            "INSERT INTO players(nickname,team_id) VALUES('E2E Compare Other',?)", (second_team,)
        ).lastrowid
        event = conn.execute(
            "INSERT INTO events(name,slug,start_date) VALUES('E2E Dot Cup','e2e-dot-cup','2026-10-01')"
        ).lastrowid
        for index in range(3):
            match = conn.execute(
                "INSERT INTO matches(event_id,team1_id,team2_id,status,team1_score,team2_score,match_time,slug,map1) VALUES(?,?,?,'completed',2,0,?,?,'de_mirage')",
                (
                    event,
                    first_team,
                    second_team,
                    f"2026-10-0{index + 1} 12:00:00",
                    f"e2e-dot-{index}",
                ),
            ).lastrowid
            for map_name in ["de_mirage", "de_nuke"] if index == 0 else ["de_mirage"]:
                conn.execute(
                    "INSERT INTO match_stats(match_id,player_id,team_id,map_name,kills,deaths,rating,rounds_played) VALUES(?,?,?,?,18,12,1.2,20)",
                    (match, player, first_team, map_name),
                )
            if index == 0:
                conn.execute(
                    "INSERT INTO match_stats(match_id,player_id,team_id,map_name,rating,rounds_played,t_rating,ct_rating) "
                    "VALUES(?,?,?,'de_mirage',1.1,20,0.8,1.4)",
                    (match, other_player, second_team),
                )
        conn.execute(
            "UPDATE match_stats SET t_rating=1.6,ct_rating=0.8 WHERE player_id=?", (player,)
        )
        from services.performance_service import refresh_player_performance

        refresh_player_performance(conn)
        conn.commit()
        conn.close()
        # 上传测试只写临时目录，不向项目原有的队标目录添加文件。
        with (
            patch(
                "blueprints.admin_catalog.save_uploaded_team_logo",
                side_effect=lambda file, _root: save_uploaded_team_logo(file, temp_dir),
            ),
            patch(
                "routes.events.save_uploaded_team_logo",
                side_effect=lambda file, _root: save_uploaded_team_logo(file, temp_dir),
            ),
            patch(
                "routes.events.remove_uploaded_team_logo",
                side_effect=lambda _root, filename: remove_uploaded_team_logo(temp_dir, filename),
            ),
        ):
            app.run(host="127.0.0.1", port=5010, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
