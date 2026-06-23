"""
A2S Server Query 实时比分轮询器

通过 Valve A2S 协议（UDP）查询 TGPro / 任意 CS2 服务器状态:
  - A2S_INFO  → 地图名、玩家数
  - A2S_PLAYER → 在线玩家名 + 得分

每 5 秒轮询一次，结果写入 live_match_data 表供 /api/live/state 读取。
服务器不需要任何配置 — A2S 默认开启。

用法:
    from utils.live_poller import start_poller
    start_poller()  # app.py 启动时调用一次
"""

import json
import socket
import struct
import sys
import threading
import time

POLL_INTERVAL = 1  # 秒

# ---------------------------------------------------------------------------
# 轻量 A2S 协议实现（不依赖第三方库，纯 socket）
# A2S_INFO 请求: 0xFF 0xFF 0xFF 0xFF 0x54 "Source Engine Query\0"
# A2S_PLAYER 请求: 0xFF 0xFF 0xFF 0xFF 0x55 + challenge (如需要)
# ---------------------------------------------------------------------------

A2S_INFO_REQUEST = b"\xff\xff\xff\xffTSource Engine Query\x00"
A2S_PLAYER_REQUEST = b"\xff\xff\xff\xffU\xff\xff\xff\xff"  # challenge=-1 获取 challenge


def _query_udp(address, payload, timeout=2.0):
    """发送 UDP 请求，返回原始字节"""
    host, port = address
    port = int(port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload, (host, port))
        data, _ = sock.recvfrom(4096)
        return data
    except (socket.timeout, OSError, ConnectionRefusedError):
        return None
    finally:
        sock.close()


def _parse_a2s_info(data):
    """
    解析 A2S_INFO 响应
    返回 dict: {map_name, player_count, max_players, server_name}
    """
    if not data or len(data) < 6 or data[4] != 0x49:
        return None
    try:
        # 跳过 header: 4 bytes 0xFF + 1 byte 0x49
        offset = 5
        # protocol version
        offset += 1
        # server name (null-terminated)
        end = data.index(b"\x00", offset)
        server_name = data[offset:end].decode("utf-8", errors="replace")
        offset = end + 1
        # map name
        end = data.index(b"\x00", offset)
        map_name = data[offset:end].decode("utf-8", errors="replace")
        offset = end + 1
        # folder (skip)
        end = data.index(b"\x00", offset)
        offset = end + 1
        # game (skip)
        end = data.index(b"\x00", offset)
        offset = end + 1
        # steam app id (2 bytes, skip)
        offset += 2
        # player count, max players
        player_count = data[offset]
        max_players = data[offset + 1]
        return {
            "server_name": server_name,
            "map_name": map_name,
            "player_count": player_count,
            "max_players": max_players,
        }
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def _get_player_challenge(address):
    """先发 A2S_PLAYER 请求获取 challenge number"""
    data = _query_udp(address, A2S_PLAYER_REQUEST, timeout=2.0)
    if not data or len(data) < 9 or data[4] != 0x41:
        return None
    # A2S_PLAYER challenge response: header(5) + 0x41 + challenge(4 bytes LE)
    return struct.unpack_from("<i", data, 5)[0]


def _parse_a2s_players(data):
    """
    解析 A2S_PLAYER 响应
    返回 list[dict]: [{name, score, duration}]
    """
    if not data or len(data) < 6 or data[4] != 0x44:
        return []
    try:
        offset = 5
        player_count = data[offset]
        offset += 1
        players = []
        for _ in range(player_count):
            # index (1 byte)
            offset += 1
            # name (null-terminated)
            end = data.index(b"\x00", offset)
            name = data[offset:end].decode("utf-8", errors="replace")
            offset = end + 1
            # score (4 bytes LE signed)
            score = struct.unpack_from("<i", data, offset)[0]
            offset += 4
            # duration (4 bytes LE float)
            duration = struct.unpack_from("<f", data, offset)[0]
            offset += 4
            players.append({"name": name, "score": score, "duration": duration})
        return players
    except (ValueError, IndexError, UnicodeDecodeError, struct.error):
        return []


def query_server(address):
    """
    查询单个服务器，返回完整状态 dict
    address: (host, port) 元组 或 "host:port" 字符串
    """
    if isinstance(address, str):
        host, port = address.rsplit(":", 1)
        address = (host.strip(), int(port))

    # A2S_INFO — 先获取 challenge（CS2 要求 challenge 握手）
    raw = _query_udp(address, A2S_INFO_REQUEST)
    if not raw:
        return {"online": False, "error": "服务器无响应"}

    if raw[4] == 0x41:  # challenge 响应
        challenge = struct.unpack_from("<i", raw, 5)[0]
        raw = _query_udp(address, A2S_INFO_REQUEST + struct.pack("<i", challenge))
        if not raw:
            return {"online": False, "error": "A2S_INFO challenge 后无响应"}

    info = _parse_a2s_info(raw)
    if not info:
        return {"online": False, "error": "无法解析 A2S_INFO"}

    challenge = _get_player_challenge(address)
    players = []
    if challenge is not None:
        player_req = b"\xff\xff\xff\xffU" + struct.pack("<i", challenge)
        players = _parse_a2s_players(_query_udp(address, player_req))
        # 过滤掉 SourceTV / GOTV 等非真实玩家
        players = [p for p in players if p.get("name", "") != "SourceTV"]
        # 按得分降序
        players.sort(key=lambda p: p["score"], reverse=True)

    # 分配队伍：>=10 人按前5后5分配；<10 人对半分配
    info["online"] = True
    info["players"] = players
    n = len(players)
    if n >= 10:
        info["team_a_players"] = players[:5]
        info["team_b_players"] = players[5:10]
    elif n > 0:
        mid = (n + 1) // 2  # ceil(n/2)
        info["team_a_players"] = players[:mid]
        info["team_b_players"] = players[mid:]
    else:
        info["team_a_players"] = []
        info["team_b_players"] = []

    return info


# ---------------------------------------------------------------------------
# 后台轮询线程
# ---------------------------------------------------------------------------

_poller_thread = None
_stop_event = threading.Event()


def _normalize_map(name):
    """标准化地图名用于匹配"""
    if not name:
        return ""
    n = name.lower().replace(" ", "_")
    for prefix in ("de_", "cs_", "workshop/"):
        if n.startswith(prefix):
            n = n[len(prefix) :]
            break
    # 去掉可能的路径后缀
    if "/" in n:
        n = n.split("/")[-1]
    return n


def _match_map_name(server_map, match_maps):
    """
    将服务器地图名匹配到比赛地图列表
    server_map: A2S 返回的 map_name（如 'de_mirage'）
    match_maps: 比赛地图列表 [(name, t1_score, t2_score), ...]
    返回匹配到的 slot (0-4) 或 None
    """
    sn = _normalize_map(server_map)
    if not sn:
        return None
    for i, (mn, _, _) in enumerate(match_maps):
        if mn and _normalize_map(mn) == sn:
            return i
    return None


def _poll_loop():
    """后台轮询主循环"""
    from models import get_db

    while not _stop_event.is_set():
        try:
            conn = get_db()
            live_matches = conn.execute("""
                SELECT id, map1, map2, map3, map4, map5,
                       map1_t1, map1_t2, map2_t1, map2_t2, map3_t1, map3_t2,
                       map4_t1, map4_t2, map5_t1, map5_t2,
                       team1_score, team2_score, server_address
                FROM matches
                WHERE server_address IS NOT NULL AND server_address != ''
                  AND COALESCE(status, '') != 'completed'
                  AND match_time IS NOT NULL AND datetime(match_time) <= datetime('now', 'localtime')
            """).fetchall()

            for m in live_matches:
                try:
                    addr_parts = m["server_address"].rsplit(":", 1)
                    if len(addr_parts) != 2:
                        continue
                    addr = (addr_parts[0].strip(), int(addr_parts[1]))

                    server_state = query_server(addr)

                    # 计算当前地图的比分（取玩家数推断 team score）
                    map_list = [
                        (m["map1"], m["map1_t1"] or 0, m["map1_t2"] or 0),
                        (m["map2"], m["map2_t1"] or 0, m["map2_t2"] or 0),
                        (m["map3"], m["map3_t1"] or 0, m["map3_t2"] or 0),
                        (m["map4"], m["map4_t1"] or 0, m["map4_t2"] or 0),
                        (m["map5"], m["map5_t1"] or 0, m["map5_t2"] or 0),
                    ]
                    slot = _match_map_name(server_state.get("map_name", ""), map_list)

                    live_data = {
                        "server": server_state,
                        "map_slot": slot,
                        "poll_time": time.time(),
                    }
                    current = conn.execute(
                        "SELECT live_state FROM live_match_data WHERE match_id=?", (m["id"],)
                    ).fetchone()
                    merged = {}
                    if current and current["live_state"]:
                        try:
                            merged = json.loads(current["live_state"])
                        except (ValueError, TypeError):
                            pass
                    merged["a2s"] = live_data
                    conn.execute(
                        """
                        INSERT INTO live_match_data(match_id, live_state)
                        VALUES(?, ?)
                        ON CONFLICT(match_id) DO UPDATE SET live_state=excluded.live_state, updated_at=CURRENT_TIMESTAMP
                    """,
                        (m["id"], json.dumps(merged, ensure_ascii=False)),
                    )

                except Exception:
                    # 单个服务器查询失败不影响其他服务器
                    pass

            conn.commit()
            try:
                conn.close()
            except Exception:
                pass

        except Exception:
            pass

        _stop_event.wait(POLL_INTERVAL)


def start_poller():
    """启动后台 A2S 轮询线程（daemon，不阻塞主进程退出）"""
    global _poller_thread
    if _poller_thread and _poller_thread.is_alive():
        return
    _stop_event.clear()
    _poller_thread = threading.Thread(target=_poll_loop, daemon=True, name="a2s-poller")
    _poller_thread.start()
    print("[LivePoller] A2S 轮询已启动（间隔 {} 秒）".format(POLL_INTERVAL), file=sys.stderr)


def stop_poller():
    """停止轮询"""
    _stop_event.set()
    if _poller_thread:
        _poller_thread.join(timeout=3)
