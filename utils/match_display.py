"""Order public opponents without renumbering the stored match sides."""

from utils.helpers import row_get


def match_opponents(match):
    opponents = []
    for number in (1, 2):
        name = str(
            row_get(match, f"team{number}_name") or row_get(match, f"t{number}n") or ""
        ).strip()
        short = str(
            row_get(match, f"t{number}s")
            or row_get(match, f"team{number}_short")
            or row_get(match, f"team{number}_short_name")
            or ""
        ).strip()
        opponents.append(
            {
                "side": f"t{number}",
                "number": number,
                "id": row_get(match, f"team{number}_id"),
                "name": name or short or "TBD",
                "short": short or name or "TBD",
                "logo": row_get(match, f"t{number}_logo") or row_get(match, f"team{number}_logo"),
                "score": row_get(match, f"team{number}_score"),
            }
        )
    return sorted(
        opponents,
        key=lambda opponent: (opponent["name"] == "TBD", opponent["short"].casefold()),
    )
