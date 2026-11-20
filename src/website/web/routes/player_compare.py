"""Public player comparison page."""

from flask import render_template, request

from src.website.domains.statistics.player_comparison import _compare_card, _compare_player
from src.website.runtime.database import get_db
from src.website.web.routing import site_routes


@site_routes.route("/players/compare")
def player_compare():
    """选手对比（照 HLTV）：左右两张卡，每项数据一行，占优的一方加粗。"""
    conn = get_db()
    all_players = conn.execute(
        "SELECT p.*, t.name AS team_name FROM players p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.nickname"
    ).fetchall()
    side_a = _compare_player(conn, request.args.get("id1", type=int))
    side_b = _compare_player(conn, request.args.get("id2", type=int))
    conn.close()
    cards = [_compare_card("a", "id1", side_a, side_b), _compare_card("b", "id2", side_b, side_a)]
    return render_template(
        "public/players/player_compare.html", all_players=all_players, cards=cards
    )
