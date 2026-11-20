"""为新比赛生成 BP 记录，并解释历史手写记录；未识别的行保留原文。"""

import re

from src.website.domains.matches.map_names import normalize_map_key


def format_bp_log(state, team1_name="TBD", team2_name="TBD"):
    """将 BP 状态转为可读文本，用于 bp_process 字段"""
    lines = []

    team_names = {"t1": team1_name, "t2": team2_name}

    rolls = state.get("rolls", {})
    t1r = rolls.get("t1")
    t2r = rolls.get("t2")
    first_picker = state.get("first_picker", "")
    first_choice = state.get("first_choice", "")

    if t1r is not None or t2r is not None:
        lines.append(
            f"Roll: {team_names['t1']}={'?' if t1r is None else t1r}, "
            f"{team_names['t2']}={'?' if t2r is None else t2r}"
            + (f" → {team_names.get(first_picker, first_picker)} 胜出" if first_picker else "")
        )

    if first_choice:
        lines.append(
            f"{team_names.get(first_picker, first_picker)} "
            f"选择{'先手' if first_choice == 'first' else '后手'}"
        )

    # action_log
    action_log = state.get("action_log", [])
    for i, entry in enumerate(action_log):
        act = "Ban" if entry["action"] == "ban" else "Pick"
        lines.append(
            f"{i + 1}. {team_names.get(entry['team'], entry['team'])} {act} {entry['map']}"
        )

    # remaining map
    picks = state.get("picks", [])
    for p in picks:
        if p.get("picked_by") == "remaining":
            lines.append(f"{len(action_log) + 1}. {p['map']} 剩余")

    # side selections
    for p in picks:
        if p.get("side"):
            side_team = p.get("side_team")
            if not side_team and p.get("picked_by") in ("t1", "t2"):
                side_team = "t2" if p["picked_by"] == "t1" else "t1"
            side_name = team_names.get(side_team, side_team or "?")
            lines.append(f"选边: {side_name} 为 {p['map']} 选择 {p['side']} 方")

    return "\n".join(lines)


_BP_ROLL = re.compile(
    r"^roll[:：]\s*(?P<a>[^=]+?)=(?P<ra>[^,，]+?)\s*[,，]\s*(?P<b>[^=]+?)=(?P<rb>\S+?)"
    r"(?:\s*→\s*(?P<win>.+?)\s*胜出)?$",
    re.I,
)
_BP_ORDER = re.compile(r"^(?P<team>.+?)\s*选择(?P<order>先手|后手)$")
_BP_STEP = re.compile(
    r"^(?:(?P<num>\d+)[.、)]\s*)?(?P<team>.+?)\s+(?P<act>ban|pick)\s+(?P<map>.+)$", re.I
)
_BP_LEFT = re.compile(
    r"^(?:(?P<num>\d+)[.、)]\s*)?(?:(?P<map>.+?)\s*剩余|(?:left|decider)\s+(?P<map2>.+))$", re.I
)
_BP_SIDE = re.compile(
    r"^选边[:：]\s*(?:(?P<team>.+?)\s+为\s+(?P<map>.+?)\s+选择\s*|(?P<map2>.+?)\s*→\s*)(?P<side>CT|T)\s*方?$",
    re.I,
)


def _bp_team_side(label, team_labels):
    """BP 记录里的队名 → 't1' / 't2'；认不出返回 None（页面直接显示原文）。"""
    key = (label or "").strip().casefold()
    for side, labels in team_labels.items():
        if key in labels:
            return side
    return None


def _bp_add_step(result, num, team_label, action, map_name, team_labels):
    """记一步禁图 / 选图 / 决胜图；没写序号的按顺序补上。"""
    result["steps"].append(
        {
            "num": int(num) if num else len(result["steps"]) + 1,
            "team": _bp_team_side(team_label, team_labels),
            "label": (team_label or "").strip(),
            "action": action,
            "map": map_name.strip(),
        }
    )


def _bp_parse_line(line, result, team_labels):
    """拆一行 BP 记录，写进 result；这一行认不出来返回 False。"""
    if m := _BP_ROLL.match(line):
        rolls = {
            _bp_team_side(m["a"], team_labels) or "t1": m["ra"],
            _bp_team_side(m["b"], team_labels) or "t2": m["rb"],
        }
        result["roll"] = {
            "t1": rolls.get("t1", "?"),
            "t2": rolls.get("t2", "?"),
            "winner": _bp_team_side(m["win"], team_labels),
        }
    elif m := _BP_ORDER.match(line):
        result["order"] = {
            "team": _bp_team_side(m["team"], team_labels),
            "label": m["team"].strip(),
            "order": m["order"],
        }
    elif m := _BP_SIDE.match(line):
        result["sides"].append(
            {
                "team": _bp_team_side(m["team"], team_labels),
                "label": (m["team"] or "").strip(),
                "map": (m["map"] or m["map2"]).strip(),
                "side": m["side"].upper(),
            }
        )
    elif m := _BP_STEP.match(line):
        _bp_add_step(result, m["num"], m["team"], m["act"].lower(), m["map"], team_labels)
    elif m := _BP_LEFT.match(line):
        _bp_add_step(result, m["num"], "", "left", m["map"] or m["map2"], team_labels)
    else:
        return False
    return True


def _bp_fill_side_teams(result):
    """旧记录的“选边”没写是谁选的：选图的对手选边；BO1 的剩余图由没做最后一次禁图的队伍选。"""
    other = {"t1": "t2", "t2": "t1"}
    pickers = {
        normalize_map_key(st["map"]): st["team"] for st in result["steps"] if st["action"] == "pick"
    }
    bans = [st["team"] for st in result["steps"] if st["action"] == "ban"]
    for side in result["sides"]:
        if side["team"] or side["label"]:
            continue
        key = normalize_map_key(side["map"])
        if key in pickers and pickers[key]:
            side["team"] = other[pickers[key]]
        elif not pickers and bans and bans[-1]:
            side["team"] = other[bans[-1]]


def parse_bp_log(text, team1_labels, team2_labels):
    """把比赛的 BP 记录文字拆成 roll / 先后手 / 步骤 / 选边；一步都认不出时返回 None（页面原样显示文字）。

    team1_labels / team2_labels：记录里可能出现的两队叫法，比如 ["T1", 队名, 简称]。
    """
    team_labels = {
        "t1": {str(x).strip().casefold() for x in team1_labels if x},
        "t2": {str(x).strip().casefold() for x in team2_labels if x},
    }
    result = {"roll": None, "order": None, "steps": [], "sides": [], "notes": []}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line and not _bp_parse_line(line, result, team_labels):
            result["notes"].append(line)
    if not result["steps"]:
        return None
    _bp_fill_side_teams(result)
    return result
