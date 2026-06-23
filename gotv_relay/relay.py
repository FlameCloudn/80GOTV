"""
GOTV 实时数据中继器
连接 CS2 服务器 GOTV TCP 端口，缓冲 demo 数据流，定时用 csda 解析球员统计。
用法: python gotv_relay/relay.py <match_id> <gotv_host:port> [--api URL]
"""

import json
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger("80gotv.gotv_relay")

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from utils.demo_parser import find_csda, get_match_info, parse_player_stats


class GotvRelay:
    def __init__(self, match_id, gotv_addr, api_base="http://127.0.0.1:5000"):
        self.match_id = match_id
        self.host, self.port = self._parse_addr(gotv_addr)
        self.api_base = api_base.rstrip("/")
        self.sock = None
        self.running = False
        self.demo_path = None  # 实时写入的 demo 文件
        self.lock = threading.Lock()
        self.parsing = False  # 防止并发解析
        self.last_push = 0
        self.push_count = 0

    def _parse_addr(self, addr):
        host, _, port = addr.partition(":")
        return host.strip(), int(port.strip() or 27016)

    def _find_csda(self):
        csda = find_csda()
        if not csda:
            raise RuntimeError("csda 未找到，请将 csda.exe 放在项目根目录")
        return csda

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(3)
        # 创建临时 demo 文件
        fd, self.demo_path = tempfile.mkstemp(suffix=".dem", prefix="gotv_live_")
        os.close(fd)
        logger.info("已连接 %s:%s，缓冲到 %s", self.host, self.port, self.demo_path)

    def _parse_and_push(self):
        """复制当前 demo 缓冲，用 csda 解析，推送到 API"""
        if self.parsing:
            return  # 上一次解析尚未完成，跳过
        if not self.demo_path or not os.path.isfile(self.demo_path):
            return
        fsize = os.path.getsize(self.demo_path)
        if fsize < 1024:  # 至少 1KB
            return
        self.parsing = True

        # 复制到临时文件（避免读写冲突）
        fd, snapshot_path = tempfile.mkstemp(suffix=".dem", prefix="gotv_snap_")
        os.close(fd)
        try:
            with self.lock:
                shutil.copy2(self.demo_path, snapshot_path)

            # 调用 csda 解析
            csda = self._find_csda()
            output_dir = tempfile.mkdtemp(prefix="csda_gotv_")
            try:
                import subprocess

                result = subprocess.run(
                    [
                        csda,
                        "-demo-path",
                        snapshot_path,
                        "-output",
                        output_dir,
                        "-format",
                        "json",
                        "-source",
                        "valve",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    # csda 可能在 demo 不完整时失败，静默跳过
                    return

                # 查找 JSON 输出
                json_files = [f for f in os.listdir(output_dir) if f.endswith(".json")]
                if not json_files:
                    return
                json_path = os.path.join(output_dir, json_files[0])
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 提取统计数据
                match_info = get_match_info(data)
                players = parse_player_stats(data)
                if not players:
                    return

                # 构建推送 payload
                payload = {
                    "match_id": self.match_id,
                    "map_name": match_info.get("map_name", ""),
                    "team_a_name": match_info.get("team_a_name", ""),
                    "team_b_name": match_info.get("team_b_name", ""),
                    "team_a_score": match_info.get("team_a_score", 0),
                    "team_b_score": match_info.get("team_b_score", 0),
                    "rounds_count": match_info.get("rounds_count", 0),
                    "halftime": match_info.get("halftime", {}),
                    "players": players,
                }
                self._post_stats(payload)

            finally:
                shutil.rmtree(output_dir, ignore_errors=True)
        finally:
            try:
                os.remove(snapshot_path)
            except OSError:
                pass
            finally:
                self.parsing = False

    def _post_stats(self, payload):
        """POST 统计数据到 Flask API"""
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{self.api_base}/api/gotv/stats",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "X-GOTV-Secret": Config.GOTV_SECRET or "",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.push_count += 1
                pl_count = len(payload.get("players", []))
                logger.info(
                    "推送 #%s: %s 名选手 → %s (%s:%s)",
                    self.push_count,
                    pl_count,
                    payload.get("map_name", "?"),
                    payload.get("team_a_score", 0),
                    payload.get("team_b_score", 0),
                )
        except urllib.error.URLError as e:
            logger.warning("推送失败: %s", e)

    def read_loop(self):
        """持续读取 GOTV 数据流"""
        self.running = True
        self.last_push = time.time()
        PUSH_INTERVAL = 5

        with open(self.demo_path, "wb") as f:
            while self.running:
                try:
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        logger.info("连接关闭")
                        break
                    with self.lock:
                        f.write(chunk)
                        f.flush()

                    # 定时推送（后台线程，不阻塞读取）
                    now = time.time()
                    if now - self.last_push >= PUSH_INTERVAL:
                        threading.Thread(target=self._parse_and_push, daemon=True).start()
                        self.last_push = now

                except socket.timeout:
                    # 即使无新数据也要定时解析
                    now = time.time()
                    if now - self.last_push >= PUSH_INTERVAL:
                        threading.Thread(target=self._parse_and_push, daemon=True).start()
                        self.last_push = now
                    continue
                except (ConnectionError, OSError) as e:
                    logger.warning("连接错误: %s", e)
                    break

    def run(self):
        """主循环（含自动重连）"""
        while True:
            try:
                self.connect()
                self.read_loop()
            except (ConnectionError, OSError, socket.timeout) as e:
                logger.warning("断开: %s，5 秒后重连...", e)
                time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("未知错误: %s，10 秒后重试...", e)
                time.sleep(10)
        self.stop()

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        if self.demo_path:
            try:
                os.remove(self.demo_path)
            except:
                pass


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] GOTV: %(message)s")

    if len(sys.argv) < 3:
        print("用法: python gotv_relay/relay.py <match_id> <gotv_host:port> [--api URL]")
        print("GOTV 端口通常 = 游戏端口 + 1，如服务器 :27015 → GOTV :27016")
        print("示例: python gotv_relay/relay.py 8 82.156.150.252:27016")
        sys.exit(1)

    match_id = int(sys.argv[1])
    gotv_addr = sys.argv[2]
    api_base = "http://127.0.0.1:5000"
    for i, arg in enumerate(sys.argv):
        if arg == "--api" and i + 1 < len(sys.argv):
            api_base = sys.argv[i + 1]

    relay = GotvRelay(match_id, gotv_addr, api_base)
    try:
        relay.run()
    except KeyboardInterrupt:
        relay.stop()
        logger.info("已停止")


if __name__ == "__main__":
    main()
