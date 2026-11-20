"""Read and sanitize the legacy live-state projection."""

from src.website.domains.matches.match_utils import get_bo_max_maps


def _strip_gsi_auth(payload):
    clean = dict(payload) if isinstance(payload, dict) else {}
    clean.pop("auth", None)
    return clean


def _sanitize_live_state(state):
    if not isinstance(state, dict):
        return {}
    clean = dict(state)
    if isinstance(clean.get("gsi"), dict):
        clean["gsi"] = _strip_gsi_auth(clean["gsi"])
    return clean


def _active_map_slots(match):
    return [
        slot
        for slot in range(get_bo_max_maps(match["bo_format"]))
        if slot < 2 or match[f"has_map{slot + 1}"]
    ]
