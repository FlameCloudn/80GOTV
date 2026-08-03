"""意见反馈 API"""

from flask import jsonify, request, session

from models import get_db
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import app


@app.route("/api/feedback/submit", methods=["POST"])
@csrf_required
def feedback_submit():
    """提交反馈"""
    if not rate_limit("feedback_submit", 10, 3600, by_ip=True):
        return jsonify({"ok": False, "error": "提交过于频繁，请稍后再试"}), 429
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    fb_type = data.get("type", "suggestion")
    contact = (data.get("contact") or "").strip()
    page_url = (data.get("page_url") or "").strip()

    if not content or len(content) < 2:
        return jsonify({"ok": False, "error": "内容太短"}), 400

    if len(content) > 2000:
        return jsonify({"ok": False, "error": "内容太长（最多2000字）"}), 400

    if fb_type not in ("bug", "suggestion", "question", "other"):
        fb_type = "suggestion"

    user_id = session.get("user_id")

    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO feedback (type, content, contact, page_url, user_agent, user_id)
               VALUES (?,?,?,?,?,?)""",
            (
                fb_type,
                content,
                contact,
                page_url,
                request.headers.get("User-Agent", "")[:500],
                user_id,
            ),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": "感谢反馈！"})
    except Exception:
        return jsonify({"ok": False, "error": "提交失败，请稍后再试"}), 500
