"""站内搜索的只读目录；全文页与快速提示共享实体及可见性。"""

from services.arg_event_service import ordinary_event_condition
from services.match_service import supplement_temp_teams
from site_core.player_directory import ACCOUNT_JOIN, IDENTITY_FIELDS
from utils.match_utils import get_sql_effective_status


def search_catalog(conn, query: str, *, suggestions: bool):
    like = f"%{query}%"
    limit = 5 if suggestions else 10
    news_where = "title LIKE ?" if suggestions else "(title LIKE ? OR content LIKE ? OR summary LIKE ?)"
    event_where = "name LIKE ?" if suggestions else "(name LIKE ? OR description LIKE ?)"
    news = conn.execute(
        f"""SELECT id,title,summary,publish_time,redirect_url FROM news WHERE {news_where}
            ORDER BY publish_time DESC LIMIT ?""",
        (like, limit) if suggestions else (like, like, like, limit),
    ).fetchall()
    events = conn.execute(
        f"""SELECT id,name,slug,description,start_date FROM events
            WHERE {ordinary_event_condition()} AND {event_where} ORDER BY start_date DESC LIMIT ?""",
        (like, limit) if suggestions else (like, like, limit),
    ).fetchall()
    players = conn.execute(
        f"""WITH directory AS (
                SELECT p.id,p.nickname,t.name AS team_name,{IDENTITY_FIELDS}
                FROM players p {ACCOUNT_JOIN} LEFT JOIN teams t ON p.team_id=t.id
            )
            SELECT id,nickname,team_name,group_username,managed_is_bashizhong_student AS is_bashizhong_student
            FROM directory d WHERE nickname LIKE ? OR group_username LIKE ? OR EXISTS (
                SELECT 1 FROM player_nickname_history h WHERE h.player_id=d.id AND h.nickname LIKE ?
            ) ORDER BY nickname LIMIT ?""",
        (like, like, like, limit),
    ).fetchall()
    teams = conn.execute(
        """SELECT id,name,short_name FROM teams WHERE name LIKE ? OR short_name LIKE ?
           ORDER BY name LIMIT ?""",
        (like, like, limit),
    ).fetchall()
    matches = conn.execute(
        f"""SELECT m.id,m.slug,m.match_time,m.team1_score,m.team2_score,m.bo_format,
                   m.event_id,m.team1_id,m.team2_id,m.team1_players,m.team2_players,
                   m.roster_snapshot,m.team1_registration_id,m.team2_registration_id,
                   t1.short_name AS t1s,t2.short_name AS t2s,
                   t1.name AS team1_name,t2.name AS team2_name,e.name AS event_name,
                   {get_sql_effective_status()}
            FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id
            LEFT JOIN teams t2 ON m.team2_id=t2.id LEFT JOIN events e ON m.event_id=e.id
            WHERE {ordinary_event_condition("e")} AND (t1.name LIKE ? OR t2.name LIKE ? OR e.name LIKE ?)
            ORDER BY m.match_time DESC LIMIT ?""",
        (like, like, like, limit),
    ).fetchall()
    return {
        "news": [dict(row) for row in news],
        "players": [dict(row) for row in players],
        "teams": [dict(row) for row in teams],
        "events": [dict(row) for row in events],
        "matches": [supplement_temp_teams(row, conn) for row in matches],
    }
