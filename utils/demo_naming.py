"""Stable filenames for saved match demos."""

import re


def normalize_event_short_name(value, event_id=None):
    """Keep demo filenames easy to read and safe on Windows."""
    short_name = str(value or "").strip().upper()
    short_name = re.sub(r"[^A-Z0-9_-]+", "_", short_name)
    short_name = re.sub(r"_+", "_", short_name).strip("_-")
    return short_name[:48] or f"EVENT_{event_id or 'NEW'}"


def normalize_demo_map_name(value, map_slot):
    """Turn a map name such as de_mirage into a safe filename part."""
    map_name = str(value or "").strip().lower()
    map_name = re.sub(r"^(de|cs)_", "", map_name)
    map_name = re.sub(r"[^a-z0-9_-]+", "_", map_name)
    map_name = re.sub(r"_+", "_", map_name).strip("_-")
    return map_name[:32] or f"map{int(map_slot) + 1}"


def build_demo_filename(match_id, map_slot, event_short_name, map_name=""):
    short_name = normalize_event_short_name(event_short_name)
    map_part = normalize_demo_map_name(map_name, map_slot)
    return f"{short_name}_{int(match_id)}_{map_part}.dem"


def build_demo_download_name(filename, map_slot, map_name=""):
    """Add the map name to a downloaded demo without renaming the saved file."""
    safe_filename = str(filename or "").strip()
    map_part = normalize_demo_map_name(map_name, map_slot)
    if not safe_filename:
        return f"{map_part}.dem"
    stem, ext = re.match(r"^(.*?)(\.[^.]+)?$", safe_filename).groups()
    ext = ext or ".dem"
    if map_part.lower() in stem.lower():
        return safe_filename
    return f"{map_part}_{stem}{ext}"
