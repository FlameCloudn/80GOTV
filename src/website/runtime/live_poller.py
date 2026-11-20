"""
A2S Server Query 实时比分轮询器

通过 Valve A2S 协议（UDP）查询 TGPro / 任意 CS2 服务器状态:
  - A2S_INFO  → 地图名、玩家数
  - A2S_PLAYER → 在线玩家名 + 得分

轮询结果只占旧现场记录中的 a2s 字段；托管比赛不通过此路径写入。
"""

import json
import logging
import socket
import struct
import threading
import time
from contextlib import closing

from src.website.runtime.database import get_db, write_transaction
from src.website.runtime.host import is_managed_event

POLL_INTERVAL = 1  # 秒
logger = logging.getLogger("80gotv")

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
    match_maps: 按赛图槽位排列的地图名
    返回匹配到的 slot (0-4) 或 None
    """
    sn = _normalize_map(server_map)
    if not sn:
        return None
    for i, mn in enumerate(match_maps):
        if mn and _normalize_map(mn) == sn:
            return i
    return None


def poll_once(conn):
    matches = conn.execute("""
        SELECT id, event_id, map1, map2, map3, map4, map5, server_address
        FROM matches WHERE server_address IS NOT NULL AND server_address != ''
          AND COALESCE(status, '') != 'completed'
          AND datetime(match_time) <= datetime('now', 'localtime')
    """).fetchall()
    for match in matches:
        if is_managed_event(conn, match["event_id"]):
            continue
        try:
            server_state = query_server(match["server_address"])
        except (ValueError, IndexError, OSError, OverflowError, struct.error):
            # 一个地址或回包无效，不应挡住这一轮的其他比赛。
            continue
        slot = _match_map_name(
            server_state.get("map_name"), [match[f"map{i}"] for i in range(1, 6)]
        )
        sample = {"server": server_state, "map_slot": slot, "poll_time": time.time()}
        # 各场的网络等待不占用写事务；只更新自己拥有的字段，保留导播和 GSI 帧。
        with write_transaction(conn):
            conn.execute(
                """
                INSERT INTO live_match_data(match_id, live_state) VALUES(?, json_object('a2s', json(?)))
                ON CONFLICT(match_id) DO UPDATE SET
                    live_state=json_set(CASE WHEN json_valid(live_state) THEN live_state ELSE '{}' END,
                                        '$.a2s', json_extract(excluded.live_state, '$.a2s')),
                    updated_at=CURRENT_TIMESTAMP
            """,
                (match["id"], json.dumps(sample, ensure_ascii=False)),
            )


def _poll_loop():
    while not _stop_event.is_set():
        try:
            with closing(get_db()) as conn:
                poll_once(conn)
        except Exception:
            logger.exception("现场轮询未完成，下一轮重新查询")
        _stop_event.wait(POLL_INTERVAL)


def start_poller():
    """启动后台 A2S 轮询线程（daemon，不阻塞主进程退出）"""
    global _poller_thread
    if _poller_thread and _poller_thread.is_alive():
        return
    _stop_event.clear()
    _poller_thread = threading.Thread(target=_poll_loop, daemon=True, name="a2s-poller")
    _poller_thread.start()
    logger.info("A2S 现场轮询已启动，间隔 %d 秒", POLL_INTERVAL)


def stop_poller():
    """停止轮询"""
    _stop_event.set()
    if _poller_thread:
        _poller_thread.join(timeout=3)
