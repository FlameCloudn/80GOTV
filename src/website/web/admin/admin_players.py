"""Player directory forms, linked account controls and playtime refresh."""

from flask import flash, redirect, render_template, request, url_for

from src.website.domains.directory import catalog
from src.website.domains.directory.player_service import merge_player_records, nickname_review
from src.website.domains.identity import accounts
from src.website.runtime.database import db, get_db
from src.website.runtime.storage import site_paths
from src.website.web.access import admin_required, csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.localization import t as ui_message

_DELETE_MESSAGE = {
    "missing": "flash.admin_catalog.player_not_found",
    "in_use": "flash.admin_catalog.this_player_is_still_used_by",
    "deleted": "flash.admin_catalog.player_deleted",
}
_PASSWORD_ERROR = {
    "too_short": "flash.admin_catalog.the_new_password_needs_at_least",
    "too_long": "flash.admin_catalog.new_password_cannot_exceed_128_characters",
    "mismatch": "flash.admin_catalog.passwords_do_not_match",
}


@admin_bp.route("/players")
@admin_required
def admin_players():
    with db() as conn:
        players = catalog.list_players(conn)
    return render_template("admin/catalog/players.html", players=players)


@admin_bp.route("/players/refresh-playtime", methods=["POST"])
@csrf_required
@admin_required
def admin_players_refresh_playtime():
    with db() as conn:
        result = catalog.refresh_directory_playtimes(conn)

    if result is None:
        flash(ui_message("flash.admin_catalog.no_players_with_a_steam_id"), "error")
    elif not result["configured"]:
        flash(ui_message("flash.admin_catalog.steam_api_is_not_configured_cannot"), "error")
    else:
        message = f"已更新 {result['refreshed']} 位选手的 CS2 时长"
        if result["unavailable"]:
            message += "；部分 Steam 资料不可见或读取失败"
        flash(message, "success")
    return redirect(url_for("admin.admin_players"))


@admin_bp.route("/players/password/<int:player_id>", methods=["GET", "POST"])
@csrf_required
@admin_required
def admin_player_password(player_id):
    with db() as conn:
        account = accounts.registered_account_for_player(conn, player_id)
        if not account:
            flash(ui_message("flash.admin_catalog.player_not_found"), "error")
            return redirect(url_for("admin.admin_players"))
        if not account["user_id"]:
            flash(ui_message("flash.admin_catalog.player_has_no_linked_website_account"), "error")
            return redirect(url_for("admin.admin_players"))
        if request.method != "POST":
            return render_template("admin/accounts/player_password.html", account=account)

        error = accounts.reset_registered_player_password(
            conn,
            account["user_id"],
            request.form.get("password", ""),
            request.form.get("password2", ""),
        )
        if error:
            flash(ui_message(_PASSWORD_ERROR[error]), "error")
            return render_template("admin/accounts/player_password.html", account=account), 400

    flash(
        ui_message(
            "flash.admin_catalog.updated_the_website_password_for_player",
            value1=account["nickname"],
        ),
        "success",
    )
    return redirect(url_for("admin.admin_players"))


def _player_form_values():
    school = request.form.get("is_bashizhong_student", "").strip()
    return catalog.PlayerEdit(
        nickname=request.form.get("nickname", "").strip(),
        group_username=request.form.get("group_username", "").strip(),
        team_id=request.form.get("team_id", "").strip(),
        steam_id=request.form.get("steam_id", "").strip(),
        is_bashizhong_student=int(school) if school in {"0", "1"} else None,
        create_account=request.form.get("create_account") == "1",
        account=accounts.InitialPlayerAccount(
            email=request.form.get("account_email", "").strip().lower(),
            password=request.form.get("password", ""),
            confirmation=request.form.get("password2", ""),
        ),
    )


def _player_form(player_id: int | None = None):
    with db() as conn:
        previous = catalog.player_for_edit(conn, player_id) if player_id is not None else None
        if player_id is not None and previous is None:
            return "选手不存在", 404
        if request.method != "POST":
            return render_template(
                "admin/catalog/players_form.html", player=previous, teams=catalog.team_choices(conn)
            )

        edit = _player_form_values()
        try:
            catalog.save_player(
                conn,
                edit,
                previous=previous,
                avatar=request.files.get("avatar"),
                data_root=site_paths().root,
            )
        except catalog.CatalogEditError as error:
            message = (
                ui_message("flash.admin_catalog.invalid_avatar_file_upload_jpg_png")
                if error.code == "invalid_avatar"
                else str(error)
            )
        except accounts.SteamAccountInUse:
            conn.rollback()
            message = ui_message("flash.admin_catalog.this_steam_id_is_linked_to")
        else:
            message = None

        if message:
            flash(message, "error")
            return render_template(
                "admin/catalog/players_form.html",
                teams=catalog.team_choices(conn),
                player={
                    "id": player_id,
                    "nickname": edit.nickname,
                    "group_username": edit.group_username,
                    "team_id": edit.team_id,
                    "steam_id": edit.steam_id,
                    "is_bashizhong_student": edit.is_bashizhong_student,
                    "avatar": previous["avatar"] if previous else None,
                    "create_account": edit.create_account,
                    "account_email": edit.account.email,
                },
            ), 400

    if player_id is not None:
        flash(ui_message("flash.admin_catalog.player_updated"), "success")
    else:
        flash("选手和登录账号添加成功" if edit.create_account else "选手添加成功", "success")
    return redirect(url_for("admin.admin_players"))


@admin_bp.route("/players/add", methods=["GET", "POST"])
@csrf_required
@admin_required
def admin_players_add():
    return _player_form()


@admin_bp.route("/players/edit/<int:player_id>", methods=["GET", "POST"])
@csrf_required
@admin_required
def admin_players_edit(player_id):
    return _player_form(player_id)


@admin_bp.route("/players/delete/<int:player_id>", methods=["POST"])
@csrf_required
@admin_required
def admin_players_delete(player_id):
    try:
        with db() as conn:
            result = catalog.delete_player(conn, player_id)
    except Exception as error:
        flash(ui_message("flash.admin_catalog.deletion_failed_value1", value1=str(error)), "error")
    else:
        flash(ui_message(_DELETE_MESSAGE[result]), "success" if result == "deleted" else "error")
    return redirect(url_for("admin.admin_players"))


@admin_bp.route("/nicknames")
@admin_required
def admin_nicknames():
    """Review canonical player nicknames and aliases."""
    conn = get_db()
    players, alias_map = nickname_review(conn)
    conn.close()
    return render_template("admin/catalog/nicknames.html", players=players, alias_map=alias_map)


@admin_bp.route("/nicknames/merge", methods=["POST"])
@csrf_required
@admin_required
def admin_nicknames_merge():
    """Merge a duplicate profile only after an explicit admin action."""
    source_id = request.form.get("source_id", "").strip()
    target_id = request.form.get("target_id", "").strip()
    if not source_id.isdigit() or not target_id.isdigit():
        flash(ui_message("flash.admin_operations.select_two_players_to_merge"), "error")
        return redirect(url_for("admin.admin_nicknames"))
    conn = get_db()
    try:
        result = merge_player_records(conn, int(source_id), int(target_id))
        conn.commit()
        flash(
            ui_message(
                "flash.admin_operations.merged_duplicate_profile_value1_into_value2",
                value1=result["source"],
                value2=result["target"],
            ),
            "success",
        )
    except Exception as exc:
        conn.rollback()
        flash(ui_message("flash.admin_operations.merge_failed_exc", exc=exc), "error")
    finally:
        conn.close()
    return redirect(url_for("admin.admin_nicknames"))
