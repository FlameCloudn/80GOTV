"""Team name display and stable abbreviations."""

import re

_TEMP_TEAM_RE = re.compile(r"^(?:team|队伍)\s*(\d+)$", re.IGNORECASE)


def team_abbr(name, short_name=""):
    """队伍占位缩写：临时队伍 TEAM X → TX；有 4 个字以内的简称就用简称；
    都没有时 “Team 某某” → T + 第二个词首字母，其余取名字前两个字。"""
    name = " ".join(str(name or "").split())
    short = str(short_name or "").strip()
    if name.upper() == "TBD":
        return "?"
    temp_match = _TEMP_TEAM_RE.match(name)
    if temp_match:
        return "T" + temp_match.group(1)
    if short and len(short) <= 4 and short.upper() != "TBD":
        return short
    words = name.split(" ")
    if len(words) >= 2 and words[0].casefold() == "team":
        return ("T" + words[1][0]).upper()
    return name[:2].upper()
