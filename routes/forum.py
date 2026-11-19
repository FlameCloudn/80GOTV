"""Forum list, thread and reply pages."""

from flask import flash, redirect, render_template, request, session, url_for

from site_core import community
from site_core.database import db
from utils.helpers import is_admin
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required, user_required
from web_app import app


def _thread_form_fields():
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    category = request.form.get("category_id", "").strip()
    category_id = int(category) if category.isdecimal() and len(category) <= 19 else None
    if category_id is not None and category_id > 2**63 - 1:
        category_id = None
    return title, content, category_id, not category


@app.route("/forum")
def forum_index():
    search_query = request.args.get("q", "").strip()
    category_slug = request.args.get("category", "").strip()
    sort_by = request.args.get("sort", "latest").strip()
    if sort_by not in community.FORUM_SORT_ORDERS:
        sort_by = "latest"
    mine_only = request.args.get("mine") == "1" and bool(session.get("user_id"))

    with db() as conn:
        categories = community.list_forum_categories(conn)
        if category_slug not in {row["slug"] for row in categories}:
            category_slug = ""
        threads, _, page, total_pages = community.list_forum_threads(
            conn,
            search_query=search_query,
            category_slug=category_slug,
            sort_by=sort_by,
            page=request.args.get("page", 1, type=int),
            per_page=25,
            user_id=session.get("user_id") if mine_only else None,
            clamp_page=True,
        )
    return render_template(
        "forum/index.html",
        threads=threads,
        page=page,
        total_pages=total_pages,
        search_query=search_query,
        categories=categories,
        category_filter=category_slug,
        sort_by=sort_by,
        mine_only=mine_only,
    )


@app.route("/forum/t/<int:thread_id>")
def forum_thread(thread_id):
    user_id = session.get("user_id")
    admin = is_admin()
    requested_page = request.args.get("page", 1, type=int)
    per_page = 20
    try:
        with db() as conn:
            thread = community.visit_forum_thread(conn, thread_id)
            # 浏览量先提交，不在读取分页回复时继续占用写锁。
            conn.commit()
            total_posts = community.count_comments(conn, "forum_thread", thread_id)
            total_pages = (total_posts + per_page - 1) // per_page
            page = min(max(1, requested_page), max(1, total_pages))
            posts = community.list_comments(
                conn,
                "forum_thread",
                thread_id,
                user_id,
                limit=per_page,
                offset=(page - 1) * per_page,
            )
    except community.CommunityError as exc:
        return str(exc), exc.status

    return render_template(
        "forum/thread.html",
        thread=thread,
        posts=posts,
        page=page,
        total_pages=total_pages,
        total_posts=total_posts,
        can_manage_thread=community.can_manage_thread(
            thread, int(user_id) if user_id else None, admin=admin
        ),
        is_forum_admin=admin,
        current_user_id=user_id,
    )


@app.route("/forum/thread/new", methods=["GET", "POST"])
@csrf_required
@user_required
def forum_new_thread():
    status = 200
    if request.method == "POST":
        if not rate_limit("forum_thread", 3, 300):
            flash("发帖过于频繁，请 5 分钟后再试", "error")
            status = 429
        else:
            title, content, category_id, use_default = _thread_form_fields()
            try:
                with db() as conn:
                    thread_id = community.create_forum_thread(
                        conn,
                        session["user_id"],
                        title,
                        content,
                        category_id,
                        use_default_category=use_default,
                    )
            except community.CommunityError as exc:
                flash(str(exc), "error")
                status = exc.status
            else:
                flash("帖子发布成功", "success")
                return redirect(url_for("forum_thread", thread_id=thread_id))

    with db() as conn:
        categories = community.list_forum_categories(conn)
    return render_template("forum/new_thread.html", categories=categories, thread=None), status


@app.route("/forum/t/<int:thread_id>/edit", methods=["GET", "POST"])
@csrf_required
def forum_edit_thread(thread_id):
    user_id = session.get("user_id")
    user_id = int(user_id) if user_id else None
    admin = is_admin()
    status = 200
    try:
        if request.method == "POST":
            title, content, category_id, _ = _thread_form_fields()
            try:
                with db() as conn:
                    community.edit_forum_thread(
                        conn, thread_id, user_id, title, content, category_id, admin=admin
                    )
            except community.CommunityError as exc:
                if exc.status != 400:
                    raise
                flash(str(exc), "error")
                status = exc.status
            else:
                flash("帖子已更新", "success")
                return redirect(url_for("forum_thread", thread_id=thread_id))

        with db() as conn:
            thread = community.get_editable_thread(conn, thread_id, user_id, admin=admin)
            categories = community.list_forum_categories(conn)
    except community.CommunityError as exc:
        if exc.status == 401:
            flash(str(exc), "error")
            return redirect(url_for("user_login", next=request.path))
        return str(exc), exc.status
    return render_template("forum/edit_thread.html", categories=categories, thread=thread), status


@app.route("/forum/t/<int:thread_id>/manage", methods=["POST"])
@csrf_required
def forum_manage_thread(thread_id):
    action = request.form.get("action", "").strip()
    user_id = session.get("user_id")
    try:
        with db() as conn:
            message = community.manage_forum_thread(
                conn,
                thread_id,
                action,
                int(user_id) if user_id else None,
                admin=is_admin(),
            )
    except community.CommunityError as exc:
        return str(exc), exc.status

    flash(message, "success")
    if action == "delete":
        return redirect(url_for("forum_index"))
    return redirect(url_for("forum_thread", thread_id=thread_id))


@app.route("/forum/t/<int:thread_id>/reply", methods=["POST"])
@csrf_required
@user_required
def forum_thread_reply(thread_id):
    redirect_to = url_for("forum_thread", thread_id=thread_id)
    try:
        with db() as conn:
            community.publish_forum_reply(
                conn,
                thread_id,
                session["user_id"],
                session.get("user_username", ""),
                request.form.get("content", "").strip(),
                consume_quota=lambda: rate_limit("forum_reply", 10, 60),
            )
    except community.CommunityError as exc:
        if exc.status == 404:
            return str(exc), exc.status
        flash(str(exc), "error")
        return redirect(redirect_to)

    flash("回复成功", "success")
    return redirect(redirect_to)
