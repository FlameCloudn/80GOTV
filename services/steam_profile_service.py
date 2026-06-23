"""Fetch public Steam profile details for players that only have a SteamID."""

import json
import os
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from utils.db_helpers import IMAGE_SIGNATURES

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_SECONDS = 24 * 60 * 60
MAX_AVATAR_BYTES = 2 * 1024 * 1024
ALLOWED_AVATAR_HOSTS = (
    "steamstatic.com",
    "akamaihd.net",
)


def _cache_path(app_root_path=None):
    root = app_root_path or APP_ROOT
    return os.path.join(root, "instance", "steam_profile_cache.json")


def _read_cache(app_root_path=None):
    path = _cache_path(app_root_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_cache(cache, app_root_path=None):
    path = _cache_path(app_root_path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _xml_text(root, tag):
    node = root.find(tag)
    return (node.text or "").strip() if node is not None else ""


def fetch_steam_public_profile(steam_id64, app_root_path=None):
    """Return public Steam XML profile fields, cached to avoid slow page loads."""
    steam_id64 = str(steam_id64 or "").strip()
    if not steam_id64.isdigit() or len(steam_id64) != 17:
        return {}

    cache = _read_cache(app_root_path)
    cached = cache.get(steam_id64)
    now = int(time.time())
    if cached and now - int(cached.get("checked_at") or 0) < CACHE_SECONDS:
        return cached.get("profile") or {}

    profile = {}
    url = f"https://steamcommunity.com/profiles/{steam_id64}/?xml=1"
    try:
        req = Request(url, headers={"User-Agent": "80GOTV/1.0"})
        with urlopen(req, timeout=3) as resp:
            raw = resp.read(256 * 1024)
        root = ET.fromstring(raw)
        profile = {
            "steam_id64": _xml_text(root, "steamID64"),
            "persona_name": _xml_text(root, "steamID"),
            "real_name": _xml_text(root, "realname"),
            "avatar": _xml_text(root, "avatarFull") or _xml_text(root, "avatarMedium"),
        }
    except Exception:
        profile = {}

    cache[steam_id64] = {"checked_at": now, "profile": profile}
    _write_cache(cache, app_root_path)
    return profile


def _avatar_extension(data):
    for signature, ext in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return "jpg" if ext == "jpeg" else ext
    return None


def _download_steam_avatar(steam_id64, avatar_url, app_root_path=None):
    avatar_url = str(avatar_url or "").strip()
    if not avatar_url:
        return None

    parsed = urlparse(avatar_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(
        host == h or host.endswith("." + h) for h in ALLOWED_AVATAR_HOSTS
    ):
        return None

    try:
        req = Request(avatar_url, headers={"User-Agent": "80GOTV/1.0"})
        with urlopen(req, timeout=3) as resp:
            data = resp.read(MAX_AVATAR_BYTES + 1)
    except Exception:
        return None

    if not data or len(data) > MAX_AVATAR_BYTES:
        return None

    ext = _avatar_extension(data)
    if not ext:
        return None

    root = app_root_path or APP_ROOT
    avatar_dir = os.path.join(root, "static", "avatars")
    os.makedirs(avatar_dir, exist_ok=True)
    filename = f"steam_{steam_id64}.{ext}"
    path = os.path.join(avatar_dir, filename)
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError:
        return None
    return filename


def enrich_player_from_steam(conn, player_or_id, app_root_path=None):
    """
    Fill empty player fields from public Steam profile data.

    The website nickname is intentionally kept as-is; Steam nicknames are not
    allowed to overwrite the user's official site nickname.
    """
    if isinstance(player_or_id, int):
        player = conn.execute("SELECT * FROM players WHERE id=?", (player_or_id,)).fetchone()
    else:
        player = player_or_id
    if not player:
        return False

    steam_id64 = str(player["steam_id"] or "").strip()
    if not steam_id64:
        return False

    needs_avatar = not (player["avatar"] or "").strip()
    needs_real_name = not (player["real_name"] or "").strip()
    if not needs_avatar and not needs_real_name:
        return False

    profile = fetch_steam_public_profile(steam_id64, app_root_path)
    if not profile:
        return False

    updates = []
    params = []
    if needs_avatar:
        avatar_file = _download_steam_avatar(steam_id64, profile.get("avatar"), app_root_path)
        if avatar_file:
            updates.append("avatar=?")
            params.append(avatar_file)
    real_name = str(profile.get("real_name") or "").strip()
    if real_name.lower() in ("none", "null") or real_name == steam_id64:
        real_name = ""
    if needs_real_name and real_name:
        updates.append("real_name=?")
        params.append(real_name[:80])

    if not updates:
        return False
    params.append(player["id"])
    conn.execute(f"UPDATE players SET {', '.join(updates)} WHERE id=?", params)
    return True
