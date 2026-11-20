"""BP 浏览器口令、参与者身份和旧 JSON 响应约定。"""

import hashlib
import hmac
from contextlib import contextmanager
from functools import wraps

from flask import jsonify, session

from src.website.domains.matches import bp_match_state as store
from src.website.domains.matches.bp_manager import get_current_step_info
from src.website.runtime.database import db
from src.website.runtime.host import HostError


def verification_marker(stored_password):
    return hashlib.sha256(str(stored_password or "").encode("utf-8")).hexdigest()


def password_verified(match):
    if not match["bp_password"]:
        return True
    marker = session.get(f"bp_verified_{match['id']}")
    return isinstance(marker, str) and hmac.compare_digest(
        marker, verification_marker(match["bp_password"])
    )


def participant_seat(conn, match, *, admin, denied_status=403):
    if admin:
        return "admin"
    if not password_verified(match):
        raise HostError("请先输入 BP 共享口令", 403)
    team = store.player_team_for_account(conn, match, session.get("user_id"))
    if not team:
        raise HostError("你未参加该比赛", denied_status)
    return team


@contextmanager
def locked_match(match_id, *, missing_status=404):
    with db() as conn:
        match = store.lock_match(conn, match_id)
        if match is None:
            raise HostError("比赛不存在", missing_status)
        yield conn, match


def state_fields(state):
    return {
        "state": state,
        "info": get_current_step_info(state),
        "bp_revision": state.get("revision", 0),
    }


def bp_json(view):
    @wraps(view)
    def respond(*args, **kwargs):
        try:
            return jsonify(view(*args, **kwargs))
        except HostError as exc:
            fields = state_fields(exc.params["state"]) if "state" in exc.params else {}
            return jsonify(ok=False, msg=exc.message, **fields), exc.status

    return respond
