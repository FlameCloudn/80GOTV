"""系列赛达成胜场数及结束条件，不依赖赛制页面或托管数据库。"""

from src.website.domains.matches.opponents import has_temp_players


def get_series_result(bo_format, score1, score2):
    """Return the two match sides only for a valid, decided BO1/BO3/BO5 result."""
    wins_needed = {"BO1": 1, "BO3": 2, "BO5": 3}.get(str(bo_format or "BO3").upper())
    if wins_needed is None:
        return None, None
    scores = []
    for value in (score1, score2):
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return None, None
        text = str(value).strip()
        if not text.isascii() or not text.isdigit():
            return None, None
        scores.append(int(text))
    if max(scores) != wins_needed or min(scores) >= wins_needed:
        return None, None
    return ("t1", "t2") if scores[0] > scores[1] else ("t2", "t1")


def completed_match_result_error(match):
    """Validate the explicit finish action without requiring map or Demo details."""
    match = dict(match)
    if match.get("status") == "cancelled":
        return "比赛已取消，不能直接结束比赛"
    winner, _ = get_series_result(
        match.get("bo_format"), match.get("team1_score"), match.get("team2_score")
    )
    if winner is None:
        return "比分尚未达到该赛制的获胜条件，或比分无效，不能结束比赛"
    for side in (1, 2):
        if not match.get(f"team{side}_id") and not has_temp_players(
            match.get(f"team{side}_players")
        ):
            return "请先确认双方参赛队伍，再结束比赛"
    if match.get("team1_id") and match.get("team1_id") == match.get("team2_id"):
        return "两支参赛队伍不能相同"
    return None
