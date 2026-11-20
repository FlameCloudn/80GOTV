"""Team directory forms and result messages."""

from flask import flash, redirect, render_template, request, url_for

from src.website.domains.directory import catalog
from src.website.runtime.database import db
from src.website.runtime.storage import site_paths
from src.website.web.access import admin_required, csrf_required
from src.website.web.admin.admin import admin_bp
from src.website.web.localization import t as ui_message

_DELETE_MESSAGE = {
    "missing": "flash.admin_catalog.team_not_found",
    "in_use": "flash.admin_catalog.this_team_is_still_used_by",
    "deleted": "flash.admin_catalog.team_deleted",
}


@admin_bp.route("/teams")
@admin_required
def admin_teams():
    with db() as conn:
        teams = catalog.list_teams(conn)
    return render_template("admin/catalog/teams.html", teams=teams)


def _team_form(team_id: int | None = None):
    if request.method != "POST" and team_id is None:
        return render_template("admin/catalog/teams_form.html", team=None)

    with db() as conn:
        team = catalog.team_for_edit(conn, team_id) if team_id is not None else None
        if team_id is not None and team is None:
            return "队伍不存在", 404
        if request.method != "POST":
            return render_template("admin/catalog/teams_form.html", team=team)

        edit = catalog.TeamEdit(
            name=request.form.get("name", "").strip(),
            short_name=request.form.get("short_name", "").strip(),
            description=request.form.get("description", "").strip(),
        )
        try:
            catalog.save_team(
                conn,
                edit,
                team_id=team_id,
                logo=request.files.get("logo"),
                data_root=site_paths().root,
            )
        except catalog.CatalogEditError as error:
            flash(str(error), "error")
            return render_template(
                "admin/catalog/teams_form.html",
                team={
                    "id": team_id,
                    "name": edit.name,
                    "short_name": edit.short_name,
                    "description": edit.description,
                    "logo": team["logo"] if team else None,
                },
            ), 400

    message = (
        "flash.admin_catalog.team_added" if team_id is None else "flash.admin_catalog.team_updated"
    )
    flash(ui_message(message), "success")
    return redirect(url_for("admin.admin_teams"))


@admin_bp.route("/teams/add", methods=["GET", "POST"])
@csrf_required
@admin_required
def admin_teams_add():
    return _team_form()


@admin_bp.route("/teams/edit/<int:team_id>", methods=["GET", "POST"])
@csrf_required
@admin_required
def admin_teams_edit(team_id):
    return _team_form(team_id)


@admin_bp.route("/teams/delete/<int:team_id>", methods=["POST"])
@csrf_required
@admin_required
def admin_teams_delete(team_id):
    try:
        with db() as conn:
            result = catalog.delete_team(conn, team_id)
    except Exception as error:
        flash(ui_message("flash.admin_catalog.deletion_failed_value1", value1=str(error)), "error")
    else:
        flash(ui_message(_DELETE_MESSAGE[result]), "success" if result == "deleted" else "error")
    return redirect(url_for("admin.admin_teams"))
