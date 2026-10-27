"""Resolve news references from public routes and local records, without HTTP requests."""

import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from flask import current_app
from werkzeug.exceptions import HTTPException

from services.match_service import supplement_temp_teams
from utils.helpers import resolve_event_ref
from utils.match_display import match_opponents


class NewsReferenceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


PUBLIC_PAGES = {
    "index": ("page", "页面", "80GOTV 首页"),
    "news_list": ("page", "页面", "新闻"),
    "matches_list": ("page", "页面", "赛程"),
    "results_list": ("page", "页面", "赛果"),
    "events_list": ("page", "页面", "赛事"),
    "players_list": ("page", "页面", "选手"),
    "teams_list": ("page", "页面", "队伍"),
    "stats_page": ("stats", "数据", "数据统计"),
    "predictions_page": ("page", "页面", "预测排行榜"),
    "awards_page": ("page", "页面", "荣誉堂"),
    "dashboard": ("stats", "数据", "数据看板"),
    "forum_index": ("page", "页面", "论坛"),
    "search": ("page", "页面", "站内搜索"),
    "player_compare": ("stats", "数据", "选手对比"),
    "games_page": ("game", "游戏", "游戏"),
    "guess_player_page": ("game", "游戏", "猜选手每日挑战"),
    "guess_player_practice_page": ("game", "游戏", "猜选手自由游玩"),
    "guess_player_multiplayer_page": ("game", "游戏", "猜选手在线对战"),
    "map_quiz_page": ("game", "游戏", "猜地图每日挑战"),
    "map_quiz_practice_page": ("game", "游戏", "猜地图自由游玩"),
    "player_bingo_page": ("game", "游戏", "选手宾果每日挑战"),
    "player_bingo_practice_page": ("game", "游戏", "选手宾果自由游玩"),
}
OVERVIEW_TITLES = {
    "best-players": "最佳选手",
    "top-events": "冠军赛事",
    "kd": "K/D",
    "pistol-rounds": "手枪局",
    "flashes": "闪光弹",
}
STAT_FILTERS = {"time", "period", "map", "side", "event", "ranking", "tab"}
PUBLIC_QUERY_KEYS = {
    "news_list": {"page"},
    "matches_list": {"event", "status", "date", "month"},
    "results_list": {"event", "page"},
    "events_list": {"status", "view"},
    "players_list": {"team", "filter", "initial"},
    "player_detail": {"period", "event"},
    "player_stats_detail": STAT_FILTERS,
    "stats_page": STAT_FILTERS | {"id1", "id2"},
    "stats_overview_detail": STAT_FILTERS,
    "player_compare": STAT_FILTERS | {"id1", "id2"},
    "event_stats": STAT_FILTERS,
    "match_detailed_stats": {"map", "tab"},
    "forum_index": {"q", "category", "sort", "page"},
    "forum_thread": {"page"},
    "search": {"q"},
}
UNSAFE_URL_CHARS = re.compile(r"[\x00-\x1f\x7f\\]")


def _split_url(value, request_host):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise NewsReferenceError("请填写有效的本站页面链接")
    if UNSAFE_URL_CHARS.search(value):
        raise NewsReferenceError("链接包含无效字符")
    value = html.unescape(value.strip())
    try:
        value.encode("utf-8")
        if UNSAFE_URL_CHARS.search(value):
            raise NewsReferenceError("链接包含无效字符")
        parsed = urlsplit(value)
        port = parsed.port
        if parsed.username is not None or parsed.password is not None:
            raise NewsReferenceError("链接不能包含账号或密码")
        if parsed.scheme or parsed.netloc:
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                raise NewsReferenceError("只支持本站公开页面链接")
            official = (parsed.hostname or "").lower() in {"80gotv.cn", "www.80gotv.cn"}
            default_port = 443 if parsed.scheme.lower() == "https" else 80
            same_host = bool(request_host) and parsed.netloc.lower() == request_host.lower()
            if not ((official and port in {None, default_port}) or same_host):
                raise NewsReferenceError("只能引用本站页面，不能引用外部网站")
        elif not value.startswith("/") or value.startswith("//"):
            raise NewsReferenceError("请填写本站路径或完整的本站页面链接")
        path = unquote(parsed.path or "/", errors="strict")
        if (
            not path.startswith("/")
            or path.startswith("//")
            or UNSAFE_URL_CHARS.search(path)
            or re.search(r"%[0-9a-fA-F]{2}", path)
            or any(part in {".", ".."} for part in path.split("/"))
        ):
            raise NewsReferenceError("链接路径无效")
        query = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=30)
        if any(UNSAFE_URL_CHARS.search(key + value) for key, value in query):
            raise NewsReferenceError("链接参数包含无效字符")
        fragment = unquote(parsed.fragment, errors="strict")
    except (ValueError, UnicodeError) as error:
        if isinstance(error, NewsReferenceError):
            raise
        raise NewsReferenceError("链接格式不正确") from error
    return path, query, fragment


def _public_suffix(endpoint, query, fragment):
    allowed = PUBLIC_QUERY_KEYS.get(endpoint, set())
    # Retain public filters, not login/return URLs, tokens or tracking parameters.
    filtered = [(key, value) for key, value in query if key in allowed and len(value) <= 200]
    suffix = "?" + urlencode(filtered) if filtered else ""
    if re.fullmatch(r"[\w:.-]{1,128}", fragment):
        suffix += "#" + quote(fragment, safe=":.-_")
    return suffix


def _match(conn, ref):
    value = str(ref)
    if value.isdecimal():
        identity = conn.execute("SELECT id FROM matches WHERE id=?", (int(value),)).fetchone()
    else:
        identity = conn.execute("SELECT id FROM matches WHERE slug=?", (value,)).fetchone()
        if not identity:
            identity = conn.execute(
                "SELECT match_id AS id FROM match_slug_aliases WHERE slug=?", (value,)
            ).fetchone()
    if not identity:
        raise NewsReferenceError("引用的比赛不存在", 404)
    row = conn.execute(
        """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
                  t1.short_name AS t1s, t2.short_name AS t2s
           FROM matches m
           LEFT JOIN teams t1 ON t1.id=m.team1_id
           LEFT JOIN teams t2 ON t2.id=m.team2_id WHERE m.id=?""",
        (identity["id"],),
    ).fetchone()
    if not row:
        raise NewsReferenceError("引用的比赛不存在", 404)
    return supplement_temp_teams(row, conn)


def resolve_news_reference(conn, value, request_host=None, _seen=None):
    path, query, fragment = _split_url(value, request_host)
    seen = set(_seen or ())
    if path in seen or len(seen) >= 8:
        raise NewsReferenceError("引用页面存在循环跳转，请直接填写目标页面链接")
    seen.add(path)
    try:
        endpoint, values = current_app.url_map.bind("localhost").match(path, method="GET")
    except HTTPException as error:
        raise NewsReferenceError("引用的页面不存在或不能公开访问", 404) from error

    for value in values.values():
        number = str(value)
        if number.isdigit() and (not number.isdecimal() or int(number) > 9223372036854775807):
            raise NewsReferenceError("引用的页面不存在", 404)

    url = quote(path, safe="/:-._~")
    if endpoint in PUBLIC_PAGES:
        kind, label, title = PUBLIC_PAGES[endpoint]
    elif endpoint in {"match_detail", "match_detailed_stats", "match_report", "match_live"}:
        match = _match(conn, values.get("slug", values.get("match_id")))
        left_team, right_team = match_opponents(match)
        title = f"{left_team['name']} vs {right_team['name']}"
        kind, label = "match", "比赛"
        url = f"/matches/{match['id']}"
        if endpoint == "match_report":
            kind, label, url = "report", "战报", url + "/report"
        elif endpoint == "match_detailed_stats":
            kind, label, url = "match_stats", "比赛数据", url + "/detailed"
    elif endpoint in {"event_detail", "event_stats"}:
        event = resolve_event_ref(conn, values["event_id"])
        if not event:
            raise NewsReferenceError("引用的赛事不存在", 404)
        kind, label, title = "event", "赛事", event["name"]
        url = f"/events/{event['id']}"
        if endpoint == "event_stats":
            kind, label, url = "event_stats", "赛事数据", url + "/stats"
    elif endpoint in {"player_detail", "player_stats_detail"}:
        player = conn.execute(
            "SELECT id, nickname FROM players WHERE id=?", (values["player_id"],)
        ).fetchone()
        if not player:
            raise NewsReferenceError("引用的选手不存在", 404)
        kind, label, title = "player", "选手", player["nickname"]
        url = f"/players/{player['id']}"
        if endpoint == "player_stats_detail":
            kind, label, url = "player_stats", "选手数据", f"/stats/players/{player['id']}"
    elif endpoint == "team_detail":
        team = conn.execute(
            "SELECT id, name FROM teams WHERE id=?", (values["team_id"],)
        ).fetchone()
        if not team:
            raise NewsReferenceError("引用的队伍不存在", 404)
        kind, label, title = "team", "队伍", team["name"]
        url = f"/teams/{team['id']}"
    elif endpoint == "news_detail":
        news = conn.execute(
            "SELECT id, title, redirect_url FROM news WHERE id=?", (values["news_id"],)
        ).fetchone()
        if not news:
            raise NewsReferenceError("引用的新闻不存在", 404)
        if news["redirect_url"]:
            return resolve_news_reference(conn, news["redirect_url"], request_host, seen)
        kind, label, title = "news", "新闻", news["title"]
        url = f"/news/{news['id']}"
    elif endpoint == "forum_thread":
        thread = conn.execute(
            """SELECT t.id, t.title FROM forum_threads t
               JOIN forum_categories c ON c.id=t.category_id
               JOIN users u ON u.id=t.user_id WHERE t.id=?""",
            (values["thread_id"],),
        ).fetchone()
        if not thread:
            raise NewsReferenceError("引用的帖子不存在", 404)
        kind, label, title = "forum_thread", "帖子", thread["title"]
        url = f"/forum/t/{thread['id']}"
    elif endpoint == "stats_overview_detail" and values["section"] in OVERVIEW_TITLES:
        kind, label, title = "stats", "数据", OVERVIEW_TITLES[values["section"]]
    else:
        raise NewsReferenceError("此地址不是可引用的本站公开内容页面")
    return {
        "url": url + _public_suffix(endpoint, query, fragment),
        "type": kind,
        "label": label,
        "title": str(title or "").strip() or label,
    }


def _reference_html(reference):
    return (
        '<div class="news-reference"><a href="' + html.escape(reference["url"], quote=True) + '">'
        '<span class="news-reference-type">' + html.escape(reference["label"]) + "</span>"
        '<strong class="news-reference-title">' + html.escape(reference["title"]) + "</strong>"
        "</a></div>"
    )


class _ReferenceParser(HTMLParser):
    """Rebuild marked blocks while leaving already-sanitized ordinary content alone."""

    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, conn, request_host, content):
        super().__init__(convert_charrefs=False)
        self.conn = conn
        self.request_host = request_host
        self.content = content
        self.line_offsets = [0] + [match.end() for match in re.finditer("\n", content)]
        self.replacements = []
        self.block_start = 0
        self.stack = []
        self.links = []
        self.block_count = 0

    def _offset(self):
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        marked = any(
            name == "class" and "news-reference" in (value or "").split() for name, value in attrs
        )
        if (marked or self.stack) and len({name for name, _ in attrs}) != len(attrs):
            raise NewsReferenceError("新闻引用块包含重复属性，请移除后重新插入")
        attrs = dict(attrs)
        if marked:
            if tag != "div" or self.stack:
                raise NewsReferenceError("新闻引用块格式不正确，请移除后重新插入")
            self.block_count += 1
            if self.block_count > 100:
                raise NewsReferenceError("一篇新闻最多插入 100 个页面引用")
            self.block_start = self._offset()
            self.stack = [tag]
            self.links = []
        elif self.stack:
            if tag == "a":
                self.links.append(attrs.get("href"))
            if tag not in self.VOID_TAGS:
                self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        if self.stack[-1] != tag:
            raise NewsReferenceError("新闻引用块格式不正确，请移除后重新插入")
        self.stack.pop()
        if not self.stack:
            if len(self.links) != 1 or not self.links[0]:
                raise NewsReferenceError("每个新闻引用块必须包含一个有效的本站页面链接")
            reference = resolve_news_reference(self.conn, self.links[0], self.request_host)
            end = self.content.index(">", self._offset()) + 1
            self.replacements.append((self.block_start, end, _reference_html(reference)))


def normalize_news_reference_blocks(conn, content, request_host=None):
    if "news-reference" not in content:
        return content
    parser = _ReferenceParser(conn, request_host, content)
    parser.feed(content)
    parser.close()
    if parser.stack:
        raise NewsReferenceError("新闻引用块不完整，请移除后重新插入")
    # Only replace parsed reference spans; do not reserialize the author's other HTML/text.
    output = []
    previous = 0
    for start, end, replacement in parser.replacements:
        output.extend((content[previous:start], replacement))
        previous = end
    output.append(content[previous:])
    return "".join(output)
