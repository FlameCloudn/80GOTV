"""Public team list and team match record pages."""

from flask import abort, render_template

from src.website.domains.matches.match_utils import get_sql_effective_status
from src.website.domains.matches.opponents import supplement_temp_teams
from src.website.domains.statistics.performance_service import summary_metric_sql
from src.website.domains.statistics.stats_storage import stats_relation
from src.website.runtime.database import get_db
from src.website.web.routing import site_routes


@site_routes.route("/teams")
def teams_list():
    """队伍列表（公开）：每支队伍带上当前阵容，列表里显示队员小头像。"""
    conn = get_db()
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    roster_rows = conn.execute(
        """SELECT id, nickname, avatar, team_id FROM players
           WHERE team_id IS NOT NULL ORDER BY nickname, id"""
    ).fetchall()
    conn.close()
    rosters = {}
    for row in roster_rows:
        rosters.setdefault(row["team_id"], []).append(row)
    return render_template("public/teams/teams_public.html", teams=teams, rosters=rosters)


def _team_record(matches, team_id):
    """按本队视角统计已结束比赛的胜 / 负 / 平（0:0 或没填比分的不算）。"""
    record = {"wins": 0, "losses": 0, "draws": 0, "finished": 0}
    for match in matches:
        first, second = match["team1_score"], match["team2_score"]
        if (
            match["effective_status"] != "completed"
            or first is None
            or second is None
            or first == second == 0
        ):
            continue
        record["finished"] += 1
        if first == second:
            record["draws"] += 1
        elif (first > second) == (match["team1_id"] == team_id):
            record["wins"] += 1
        else:
            record["losses"] += 1
    return record


@site_routes.route("/teams/<int:team_id>")
def team_detail(team_id):
    """展示指定队伍、当前阵容（带生涯 Rating）和实际以该队伍身份参加的比赛。"""
    conn = get_db()
    try:
        team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
        if team is None:
            abort(404)
        players = conn.execute(
            f"""SELECT p.id, p.nickname, p.avatar, s.maps,
                      {summary_metric_sql("avg_rating", "rating", stats_source=stats_relation(conn))} AS avg_rating
               FROM players p
               LEFT JOIN player_performance_summary s ON s.player_id=p.id
               WHERE p.team_id=? ORDER BY p.nickname, p.id""",
            (team_id,),
        ).fetchall()
        rows = conn.execute(
            f"""SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
                       t1.short_name AS t1s, t2.short_name AS t2s,
                       t1.logo AS t1_logo, t2.logo AS t2_logo,
                       e.name AS event_name, {get_sql_effective_status()}
                FROM matches m
                LEFT JOIN teams t1 ON t1.id=m.team1_id
                LEFT JOIN teams t2 ON t2.id=m.team2_id
                LEFT JOIN events e ON e.id=m.event_id
                WHERE m.team1_id=? OR m.team2_id=?
                ORDER BY m.match_time DESC, m.id DESC""",
            (team_id, team_id),
        ).fetchall()
        matches = [supplement_temp_teams(row, conn) for row in rows]
    finally:
        conn.close()
    return render_template(
        "public/teams/team_detail.html",
        team=team,
        players=players,
        matches=matches,
        record=_team_record(matches, team_id),
    )
