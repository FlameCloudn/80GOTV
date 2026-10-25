"""意见反馈 API"""

from urllib.parse import urlsplit

from flask import jsonify, request, session

from models import get_db
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import app

MAX_FEEDBACK_CONTACT_LENGTH = 254
MAX_FEEDBACK_PAGE_URL_LENGTH = 2048


def _feedback_page_path(value):
    """只保留站内页面路径，避免把查询凭证或片段写进反馈记录。"""
    if not value:
        return ""
    if "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.path.startswith("//") or (parsed.netloc and not parsed.scheme):
        return None
    if parsed.scheme and (parsed.scheme.lower() not in ("http", "https") or not parsed.netloc):
        return None
    path = parsed.path or "/"
    return path if path.startswith("/") else None


@app.route("/api/feedback/submit", methods=["POST"])
@csrf_required
def feedback_submit():
    """提交反馈"""
    if not rate_limit("feedback_submit", 10, 3600, by_ip=True):
        return jsonify({"ok": False, "error": "提交过于频繁，请稍后再试"}), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or any(
        key in data and not isinstance(data[key], str)
        for key in ("content", "type", "contact", "page_url")
    ):
        return jsonify({"ok": False, "error": "反馈格式无效，请检查后重试"}), 400
    content = data.get("content", "").strip()
    fb_type = data.get("type", "suggestion")
    contact = data.get("contact", "").strip()
    page_url = data.get("page_url", "").strip()

    if len(contact) > MAX_FEEDBACK_CONTACT_LENGTH:
        return jsonify({"ok": False, "error": "联系方式最多 254 个字符"}), 400
    if len(page_url) > MAX_FEEDBACK_PAGE_URL_LENGTH:
        return jsonify({"ok": False, "error": "页面地址过长"}), 400
    page_path = _feedback_page_path(page_url)
    if page_path is None:
        return jsonify({"ok": False, "error": "页面地址格式无效"}), 400

    if not content or len(content) < 2:
        return jsonify({"ok": False, "error": "内容太短"}), 400

    if len(content) > 2000:
        return jsonify({"ok": False, "error": "内容太长（最多2000字）"}), 400

    if fb_type not in ("bug", "suggestion", "question", "other"):
        fb_type = "suggestion"

    user_id = session.get("user_id")

    conn = None
    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO feedback (type, content, contact, page_url, user_agent, user_id)
               VALUES (?,?,?,?,?,?)""",
            (
                fb_type,
                content,
                contact,
                page_path,
                request.headers.get("User-Agent", "")[:500],
                user_id,
            ),
        )
        conn.commit()
        return jsonify({"ok": True, "message": "感谢反馈！"})
    except Exception:
        return jsonify({"ok": False, "error": "提交失败，请稍后再试"}), 500
    finally:
        if conn is not None:
            conn.close()
