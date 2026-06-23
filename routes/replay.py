"""Demo parsing API and 2D replay page."""

import json
import os
import re
import subprocess
from urllib.parse import parse_qs, urlparse

from flask import abort, jsonify, render_template, request, send_from_directory

from models import get_db
from services.match_service import supplement_temp_teams
from utils.demo_naming import build_demo_download_name
from utils.helpers import map_display_name, map_display_name_cn, resolve_match_slug, row_get
from utils.rate_limiter import rate_limit
from utils.web_helpers import csrf_required
from web_app import DEMOS_DIR, app, logger

REPLAY_CACHE_DIR = os.path.join(app.instance_path, "replay_cache")
REPLAY_MESSAGES_CACHE_DIR = os.path.join(app.instance_path, "replay_messages_cache")
REPLAY_TOOL_DIR = os.path.join(app.static_folder, "replay_tool")
REPLAY_MESSAGES_TOOL = os.path.join(app.root_path, "resources", "tools", "cs2demo-messages.exe")


def _map_name_for_slot(match, slot):
    return row_get(match, f"map{slot + 1}", "") if match else ""


def _map_label(map_name, slot):
    if not map_name:
        return f"地图 {slot + 1}"
    name_en = map_display_name(map_name)
    name_cn = map_display_name_cn(map_name)
    if name_cn and name_cn != name_en:
        return f"{name_en} / {name_cn}"
    return name_en or f"地图 {slot + 1}"


def _build_demo_options(demo_list, match=None):
    """整理页面可选 Demo，跳过空位和不安全的文件名。"""
    options = []
    if not isinstance(demo_list, list):
        return options
    for slot, item in enumerate(demo_list):
        filename = item.get("filename") if isinstance(item, dict) else item
        if not isinstance(filename, str) or not filename.strip():
            continue
        filename = filename.strip()
        if os.path.basename(filename) != filename:
            continue
        demo_path = os.path.join(DEMOS_DIR, filename)
        size_bytes = os.path.getsize(demo_path) if os.path.isfile(demo_path) else 0
        size_label = f"{size_bytes / (1024 * 1024):.1f} MB" if size_bytes else ""
        map_name = _map_name_for_slot(match, slot)
        map_label = _map_label(map_name, slot)
        options.append(
            {
                "slot": slot,
                "filename": filename,
                "download_name": build_demo_download_name(filename, slot, map_name),
                "map_name": map_name,
                "map_label": map_label,
                "size_bytes": size_bytes,
                "size_label": size_label,
                "label": f"{map_label} · {filename}",
            }
        )
    return options


def _demo_info_for_slot(match_id, slot):
    conn = get_db()
    match = conn.execute(
        "SELECT demo_file, map1, map2, map3, map4, map5 FROM matches WHERE id=?",
        (match_id,),
    ).fetchone()
    conn.close()
    if not match:
        return None, "比赛不存在", 404
    try:
        demo_list = json.loads(match["demo_file"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return None, "Demo 列表损坏", 500
    if slot < 0 or slot >= len(demo_list):
        return None, "Demo 不存在", 404
    demo_item = demo_list[slot]
    demo_filename = demo_item.get("filename") if isinstance(demo_item, dict) else demo_item
    if not isinstance(demo_filename, str) or os.path.basename(demo_filename) != demo_filename:
        return None, "Demo 文件名无效", 400
    demo_path = os.path.join(DEMOS_DIR, demo_filename)
    if not os.path.isfile(demo_path):
        return None, "Demo 文件不存在", 404
    map_name = _map_name_for_slot(match, slot)
    return (
        {
            "filename": demo_filename,
            "map_name": map_name,
            "download_name": build_demo_download_name(demo_filename, slot, map_name),
        },
        "",
        200,
    )


def _demo_filename_for_slot(match_id, slot):
    info, msg, status = _demo_info_for_slot(match_id, slot)
    return (info["filename"] if info else None), msg, status


def _demo_info_from_download_url(raw_url):
    raw_url = (raw_url or "").strip()
    if not raw_url:
        abort(400, description="缺少 Demo 地址")
    parsed = urlparse(raw_url)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        abort(400, description="Demo 地址无效")
    if parsed.netloc and parsed.netloc != request.host:
        abort(400, description="只能读取本站 Demo")
    match = re.fullmatch(r"/matches/([^/]+)/download-demo", parsed.path or "")
    if not match:
        abort(400, description="只能读取本站 Demo")
    match_id = resolve_match_slug(match.group(1))
    if not match_id:
        abort(404, description="比赛不存在")
    query = parse_qs(parsed.query or "")
    try:
        slot = int((query.get("slot") or ["0"])[0])
    except (TypeError, ValueError):
        abort(400, description="Demo 序号无效")
    demo_info, msg, status = _demo_info_for_slot(match_id, slot)
    if not demo_info:
        abort(status, description=msg)
    return match_id, slot, demo_info


def _parse_replay_messages(match_id, slot, demo_info):
    if not os.path.isfile(REPLAY_MESSAGES_TOOL):
        return None, "服务器缺少回放解析工具", 500, False

    demo_path = os.path.join(DEMOS_DIR, demo_info["filename"])
    source_stat = os.stat(demo_path)
    source_key = {"mtime_ns": source_stat.st_mtime_ns, "size": source_stat.st_size}

    os.makedirs(REPLAY_MESSAGES_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(REPLAY_MESSAGES_CACHE_DIR, f"match_{match_id}_slot_{slot}.json")
    try:
        with open(cache_path, "r", encoding="utf-8") as cache_file:
            cached = json.load(cache_file)
        if cached.get("source") == source_key and cached.get("messages"):
            return cached["messages"], "", 200, True
    except (OSError, ValueError, TypeError):
        pass

    try:
        result = subprocess.run(
            [REPLAY_MESSAGES_TOOL, demo_path],
            cwd=app.root_path,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "回放解析超时", 504, False

    if result.returncode != 0:
        logger.error("回放解析工具失败: %s", (result.stderr or result.stdout)[-2000:])
        return None, "回放解析失败", 500, False

    messages = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not messages:
        logger.error("回放解析没有输出消息: %s", (result.stderr or "")[-2000:])
        return None, "回放解析没有输出消息", 500, False

    try:
        with open(cache_path, "w", encoding="utf-8") as cache_file:
            json.dump({"source": source_key, "messages": messages}, cache_file)
    except OSError:
        logger.exception("回放消息缓存写入失败")

    return messages, "", 200, False


@app.route("/replay-tool/")
@app.route("/replay-tool/<path:filename>")
def replay_tool_static(filename="index.html"):
    """内嵌第三方 2D Demo 播放器的静态页面。"""
    target = os.path.join(REPLAY_TOOL_DIR, filename)
    if filename and os.path.isfile(target):
        return send_from_directory(REPLAY_TOOL_DIR, filename)
    index_path = os.path.join(REPLAY_TOOL_DIR, "index.html")
    if os.path.isfile(index_path):
        return send_from_directory(REPLAY_TOOL_DIR, "index.html")
    return "回放工具尚未构建", 404


@app.route("/replay-tool-proxy/download")
def replay_tool_download_proxy():
    """只代理本站保存的 Demo，供嵌入播放器读取。"""
    _match_id, _slot, demo_info = _demo_info_from_download_url(request.args.get("url"))
    demo_filename = demo_info["filename"]
    response = send_from_directory(
        DEMOS_DIR,
        demo_filename,
        as_attachment=True,
        download_name=demo_info["download_name"],
    )
    response.headers["X-Demo-Length"] = str(os.path.getsize(os.path.join(DEMOS_DIR, demo_filename)))
    return response


@app.route("/api/replay/messages")
def api_replay_messages():
    """后端解析 Demo，返回播放器可以直接使用的消息。"""
    match_id, slot, demo_info = _demo_info_from_download_url(request.args.get("url"))
    messages, msg, status, cached = _parse_replay_messages(match_id, slot, demo_info)
    if not messages:
        return jsonify({"ok": False, "msg": msg}), status
    return jsonify(
        {
            "ok": True,
            "cached": cached,
            "download_name": demo_info["download_name"],
            "message_count": len(messages),
            "messages": messages,
        }
    )


@app.route("/api/replay/parse/<int:match_id>/<int:slot>", methods=["POST"])
@csrf_required
def api_replay_parse(match_id, slot):
    """解析管理员保存的 Demo；文件未变化时直接使用缓存。"""
    if not rate_limit(f"replay_parse:{match_id}:{slot}", 6, 60, by_ip=True):
        return jsonify({"ok": False, "msg": "解析请求过于频繁，请稍后再试"}), 429

    conn = get_db()
    match = conn.execute("SELECT demo_file FROM matches WHERE id=?", (match_id,)).fetchone()
    conn.close()
    if not match:
        return jsonify({"ok": False, "msg": "比赛不存在"}), 404
    try:
        demo_list = json.loads(match["demo_file"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return jsonify({"ok": False, "msg": "Demo 列表损坏"}), 500
    if slot < 0 or slot >= len(demo_list):
        return jsonify({"ok": False, "msg": "Demo 不存在"}), 404

    demo_filename, msg, status = _demo_filename_for_slot(match_id, slot)
    if not demo_filename:
        return jsonify({"ok": False, "msg": msg}), status
    demo_path = os.path.join(DEMOS_DIR, demo_filename)

    os.makedirs(REPLAY_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(REPLAY_CACHE_DIR, f"match_{match_id}_slot_{slot}.json")
    source_stat = os.stat(demo_path)
    source_key = {"mtime_ns": source_stat.st_mtime_ns, "size": source_stat.st_size}
    try:
        with open(cache_path, "r", encoding="utf-8") as cache_file:
            cached = json.load(cache_file)
        if cached.get("source") == source_key and cached.get("data"):
            return jsonify({"ok": True, "data": cached["data"], "cached": True})
    except (OSError, ValueError, TypeError):
        pass

    try:
        from utils.replay_parser import parse_demo_replay

        data = parse_demo_replay(demo_path, tick_sample=8)
        if data is None:
            return jsonify({"ok": False, "msg": "Demo 解析失败"}), 422
        with open(cache_path, "w", encoding="utf-8") as cache_file:
            json.dump({"source": source_key, "data": data}, cache_file, ensure_ascii=False)
        return jsonify({"ok": True, "data": data})
    except Exception:
        logger.exception("Demo 回放解析失败")
        return jsonify({"ok": False, "msg": "解析失败，请管理员检查服务器日志"}), 500


@app.route("/matches/<slug>/replay")
def match_replay_page(slug):
    """2D Demo 回放页"""
    match_id = resolve_match_slug(slug)
    if not match_id:
        return "比赛不存在", 404
    conn = get_db()
    match = conn.execute(
        """
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.short_name AS t1s, t2.short_name AS t2s,
               t1.logo AS t1_logo, t2.logo AS t2_logo,
               e.name AS event_name
        FROM matches m LEFT JOIN teams t1 ON m.team1_id=t1.id
        LEFT JOIN teams t2 ON m.team2_id=t2.id
        LEFT JOIN events e ON m.event_id=e.id
        WHERE m.id=?
    """,
        (match_id,),
    ).fetchone()
    if not match:
        conn.close()
        return "比赛不存在", 404
    match = supplement_temp_teams(match, conn)
    demo_file = match["demo_file"] or ""
    demos = []
    try:
        demos = json.loads(demo_file) if demo_file else []
    except (json.JSONDecodeError, TypeError):
        pass
    conn.close()
    return render_template(
        "match_replay.html", match=match, demos=_build_demo_options(demos, match)
    )
