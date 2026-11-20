"""用户资料、学校身份与密码。"""

import logging
from contextlib import closing

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from src.website.domains.directory.player_page_queries import account_player_history
from src.website.domains.identity import accounts
from src.website.runtime.database import get_db
from src.website.runtime.storage import site_paths
from src.website.runtime.uploads import remove_uploaded_avatar, save_uploaded_avatar
from src.website.web.access import csrf_required, user_required
from src.website.web.localization import t as ui_message
from src.website.web.routes.session_navigation import _safe_next_target
from src.website.web.routes.steam_login import _get_verified_steam_id
from src.website.web.routing import site_routes

logger = logging.getLogger("80gotv")

_NICKNAME_ERRORS = {
    "length": "flash.auth.nicknames_must_be_2_20_characters",
    "taken": "flash.auth.this_nickname_is_taken",
}
_PASSWORD_ERRORS = {
    "wrong_password": "flash.auth.wrong_current_password",
    "too_short": "flash.auth.the_new_password_needs_at_least",
    "mismatch": "flash.auth.the_new_passwords_do_not_match",
}


def _validate_group_username(value):
    raw_value = str(value or "")
    group_username = raw_value.strip()
    if not group_username:
        return "", "请填写群内用户名"
    if any(character in raw_value for character in ("\r", "\n", "\t")):
        return "", "群内用户名不能包含换行或制表符"
    if len(group_username) > 40:
        return "", "群内用户名最多 40 个字符"
    return group_username, ""


def _parse_school_status(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "yes", "true"}:
        return 1
    if normalized in {"0", "no", "false"}:
        return 0
    return None


@site_routes.route("/account/complete-profile", methods=["POST"])
@csrf_required
@user_required
def complete_account_profile():
    """老账号登录后用不可关闭的弹窗补齐校内身份和必要的群昵称。"""
    school_status = _parse_school_status(request.form.get("is_bashizhong_student"))
    next_target = _safe_next_target()
    if school_status is None:
        flash(ui_message("flash.auth.choose_whether_you_are_or_were"), "error")
        return redirect(next_target)

    group_username = ""
    if school_status == 1:
        group_username, error = _validate_group_username(request.form.get("group_username", ""))
        if error:
            flash(error, "error")
            return redirect(next_target)

    with closing(get_db()) as conn:
        user = accounts.profile_account(conn, session["user_id"])
        if not user:
            session.clear()
            return redirect(url_for("user_login"))
        accounts.save_school_identity(conn, user, school_status, group_username)
        conn.commit()

    session.pop("profile_completion_required", None)
    session.pop("group_username_required", None)
    flash(ui_message("flash.auth.details_saved"), "success")
    return redirect(next_target)


def _save_profile_avatar(conn, user):
    upload = request.files.get("avatar")
    if not upload or not upload.filename:
        flash(ui_message("flash.auth.choose_an_image"), "error")
        return
    data_root = site_paths().root
    filename, _ = save_uploaded_avatar(upload, data_root)
    if not filename:
        flash(ui_message("flash.auth.invalid_file_upload_a_png_jpg"), "error")
        return

    # A failed database update must leave the previous profile image available.
    try:
        accounts.set_profile_avatar(conn, user, filename)
        conn.commit()
    except Exception:
        conn.rollback()
        remove_uploaded_avatar(data_root, filename)
        raise
    remove_uploaded_avatar(data_root, user["avatar"])
    flash(ui_message("flash.auth.avatar_updated"), "success")


def _save_profile_form(conn, user):
    action = request.form.get("action", "")
    if accounts.profile_completion_required(user) and action != "group_username":
        flash(ui_message("flash.auth.finish_your_account_details_first"), "error")
        return

    if action == "nickname":
        nickname = request.form.get("nickname", "").strip()
        error = accounts.change_profile_nickname(conn, user, nickname)
        if error:
            flash(ui_message(_NICKNAME_ERRORS[error]), "error")
            return
        conn.commit()
        session["user_username"] = nickname
        flash(ui_message("flash.auth.nickname_updated"), "success")

    elif action == "group_username":
        if user["is_bashizhong_student"] != 1:
            flash(ui_message("flash.auth.external_players_do_not_need_a"), "error")
            return
        group_username, error = _validate_group_username(request.form.get("group_username", ""))
        if error:
            flash(error, "error")
            return
        try:
            accounts.save_school_identity(conn, user, 1, group_username)
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("同步群内用户名失败")
            flash(ui_message("flash.auth.could_not_save_please_try_again"), "error")
        else:
            session.pop("profile_completion_required", None)
            session.pop("group_username_required", None)
            flash(ui_message("flash.auth.group_nickname_updated"), "success")

    elif action == "password":
        error = accounts.change_profile_password(
            conn,
            user["id"],
            request.form.get("old_password", ""),
            request.form.get("new_password", ""),
            request.form.get("new_password2", ""),
        )
        if error:
            flash(ui_message(_PASSWORD_ERRORS[error]), "error")
            return
        conn.commit()
        flash(ui_message("flash.auth.password_updated"), "success")

    elif action == "avatar":
        _save_profile_avatar(conn, user)


@site_routes.route("/profile", methods=["GET", "POST"])
@csrf_required
@user_required
def user_profile():
    with closing(get_db()) as conn:
        user = accounts.profile_account(conn, session["user_id"])
        if not user:
            return redirect(url_for("user_login"))
        if request.method == "POST":
            _save_profile_form(conn, user)
            return redirect(url_for("user_profile"))
        history = account_player_history(conn, user["steam_id64"])

    return render_template("public/account/user_profile.html", user=user, **history)


@site_routes.route("/change-password", methods=["GET", "POST"])
@csrf_required
def change_password():
    """通过 Steam OpenID 验证后修改密码。"""
    steam_id64 = _get_verified_steam_id("recovery")
    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not steam_id64:
            flash(ui_message("flash.auth.verify_with_steam_first"), "error")
            return redirect(url_for("change_password"))

        if len(password) < 8:
            flash(ui_message("flash.auth.passwords_need_at_least_8_characters"), "error")
            return render_template(
                "public/account/change_password.html", steam_verified_id=steam_id64
            )

        if password != password2:
            flash(ui_message("flash.auth.the_passwords_do_not_match"), "error")
            return render_template(
                "public/account/change_password.html", steam_verified_id=steam_id64
            )

        conn = get_db()
        if not accounts.recover_password(conn, steam_id64, generate_password_hash(password)):
            conn.close()
            flash(ui_message("flash.auth.no_account_is_linked_to_this"), "error")
            session.pop("steam_verified", None)
            return redirect(url_for("change_password"))

        conn.commit()
        conn.close()
        session.pop("steam_verified", None)

        flash(ui_message("flash.auth.password_changed_your_account_is_waiting"), "success")
        return redirect(url_for("user_login"))

    return render_template("public/account/change_password.html", steam_verified_id=steam_id64)
