"""
CS Demo 分析器 — 调用 csda CLI 解析 .dem 文件并提取比赛数据
cs-demo-analyzer: https://github.com/akiver/cs-demo-analyzer
"""

import json
import os
import shutil
import subprocess
import tempfile


def find_csda():
    """查找 csda 可执行文件路径"""
    path = os.environ.get("CSDA_PATH", "csda")
    if shutil.which(path):
        return path
    for candidate in ["csda.exe", "csda"]:
        if shutil.which(candidate):
            return candidate
    # 搜索项目根目录
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in ["csda.exe", "csda"]:
        full = os.path.join(root, candidate)
        if os.path.isfile(full):
            return full
    return None


def run_analysis(demo_path, output_dir=None):
    """
    运行 csda 分析 demo 文件，返回解析后的 JSON 数据
    异常: RuntimeError（csda 未安装） / FileNotFoundError / subprocess.TimeoutExpired
    """
    csda_path = find_csda()
    if not csda_path:
        raise RuntimeError(
            "csda 未找到。请从 https://github.com/akiver/cs-demo-analyzer/releases "
            "下载 csda 并添加到 PATH，或设置 CSDA_PATH 环境变量"
        )

    if not os.path.isfile(demo_path):
        raise FileNotFoundError(f"Demo 文件不存在: {demo_path}")

    tmpdir = None
    if output_dir is None:
        tmpdir = tempfile.mkdtemp(prefix="csda_")
        output_dir = tmpdir

    os.makedirs(output_dir, exist_ok=True)

    try:
        source = os.environ.get("CSDA_SOURCE", "valve")
        result = subprocess.run(
            [
                csda_path,
                "-demo-path",
                demo_path,
                "-output",
                output_dir,
                "-format",
                "json",
                "-source",
                source,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip() or "未知错误"
            raise RuntimeError(f"csda 分析失败 (exit {result.returncode}): {stderr}")

        base = os.path.splitext(os.path.basename(demo_path))[0]
        json_path = os.path.join(output_dir, f"{base}.json")

        if not os.path.isfile(json_path):
            json_files = [f for f in os.listdir(output_dir) if f.endswith(".json")]
            if json_files:
                json_path = os.path.join(output_dir, json_files[0])
            else:
                raise RuntimeError("csda 未生成 JSON 输出，请检查 demo 文件是否有效")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    except subprocess.TimeoutExpired:
        raise RuntimeError("csda 分析超时（超过 300 秒）")
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_halftime_scores(match_data):
    """从 rounds 数据统计半场比分（teamA 视角）"""
    rounds = match_data.get("rounds", [])
    if not isinstance(rounds, list):
        rounds = []

    h1_a, h1_b = 0, 0
    h2_a, h2_b = 0, 0
    first_a_side = None
    second_half = False

    for r in rounds:
        winner_side = r.get("winnerSide", 0)
        team_a_side = r.get("teamASide", 0)
        if first_a_side is None and team_a_side:
            first_a_side = team_a_side
        elif first_a_side and team_a_side and team_a_side != first_a_side:
            second_half = True

        if not second_half:
            if winner_side == team_a_side:
                h1_a += 1
            else:
                h1_b += 1
        else:
            if winner_side == team_a_side:
                h2_a += 1
            else:
                h2_b += 1

    return {"h1_a": h1_a, "h1_b": h1_b, "h2_a": h2_a, "h2_b": h2_b}


def parse_player_stats(match_data):
    """
    从 csda JSON 解析所有选手统计数据（含 T/CT 侧数据）

    csda → DB 映射:
        name → nickname, steamId → steam_id, killCount → kills,
        deathCount → deaths, assistCount → assists,
        averageDamagePerRound → adr, averageKillPerRound → kpr,
        averageDeathPerRound → dpr, kast → kast,
        headshotPercent → headshot_percentage, hltvRating2 → rating

    T/CT stats: csda does NOT provide per-player side stats natively.
    We calculate them from kills/damages/rounds data.

    返回: list[dict]
    """
    players_data = match_data.get("players", {}) or {}
    team_a = match_data.get("teamA", {}) or {}
    team_b = match_data.get("teamB", {}) or {}
    rounds = match_data.get("rounds", [])
    if not isinstance(rounds, list):
        rounds = []
    rounds_count = max(len(rounds), 1)

    # ---- Calculate T/CT side stats from kills, damages, rounds ----
    # csda provides killerSide/attackerSide directly in kills/damages (2=T, 3=CT)
    side_kills = {}  # steam_id_str -> {'T': int, 'CT': int}
    side_deaths = {}
    side_damage = {}  # steam_id_str -> {'T': int, 'CT': int}  (total damage)
    side_rounds = {}  # steam_id_str -> {'T': int, 'CT': int}
    damage_received = {}
    rws_points = {}

    # Map steam_id -> team letter
    player_team_map = {}
    for sid, p in players_data.items():
        if not isinstance(p, dict):
            continue
        letter = (p.get("team") or {}).get("letter", "")
        player_team_map[sid] = letter

    # Initialize accumulators
    for sid in players_data:
        side_kills[sid] = {"T": 0, "CT": 0}
        side_deaths[sid] = {"T": 0, "CT": 0}
        side_damage[sid] = {"T": 0, "CT": 0}
        side_rounds[sid] = {"T": 0, "CT": 0}
        damage_received[sid] = 0
        rws_points[sid] = 0.0

    def _side_label(v):
        """2=T, 3=CT in demoinfocs common.Team"""
        return "T" if v == 2 else "CT"

    # Count rounds per side for each player (from rounds data)
    for r in rounds:
        a_side = int(r.get("teamASide", 0))
        b_side = int(r.get("teamBSide", 0))
        for sid, letter in player_team_map.items():
            side_val = a_side if letter == "A" else b_side
            if side_val in (2, 3):
                if sid in side_rounds:
                    side_rounds[sid][_side_label(side_val)] += 1

    # Count kills/deaths by side (using killerSide/victimSide directly)
    kills_list = match_data.get("kills", [])
    if isinstance(kills_list, list):
        for kill in kills_list:
            killer_sid = str(kill.get("killerSteamId", kill.get("killerSteamId64", "")))
            victim_sid = str(kill.get("victimSteamId", kill.get("victimSteamId64", "")))
            killer_side = int(kill.get("killerSide", 0))

            if killer_sid and killer_side in (2, 3) and killer_sid in side_kills:
                side_kills[killer_sid][_side_label(killer_side)] += 1

            if victim_sid and victim_sid in side_deaths:
                victim_side = int(kill.get("victimSide", 0))
                if victim_side in (2, 3):
                    side_deaths[victim_sid][_side_label(victim_side)] += 1

    # Count damage by side (using attackerSide directly)
    damages_list = match_data.get("damages", [])
    winning_rounds = {
        int(r.get("number", 0) or 0): {
            "name": str(r.get("winnerName", "") or ""),
            "side": int(r.get("winnerSide", 0) or 0),
        }
        for r in rounds
    }
    winning_round_damage = {}
    if isinstance(damages_list, list):
        for dmg in damages_list:
            attacker_sid = str(dmg.get("attackerSteamId", dmg.get("attackerSteamId64", "")))
            victim_sid = str(dmg.get("victimSteamId", dmg.get("victimSteamId64", "")))
            amount = int(dmg.get("healthDamage", 0) or 0)
            attacker_side = int(dmg.get("attackerSide", 0))
            victim_side = int(dmg.get("victimSide", 0))

            is_enemy_damage = (
                attacker_sid
                and victim_sid
                and attacker_sid != victim_sid
                and attacker_side in (2, 3)
                and victim_side in (2, 3)
                and attacker_side != victim_side
                and amount > 0
            )
            if is_enemy_damage and attacker_sid in side_damage:
                side_damage[attacker_sid][_side_label(attacker_side)] += amount
            if is_enemy_damage and victim_sid in damage_received:
                damage_received[victim_sid] += amount

            round_num = int(dmg.get("roundNumber", 0) or 0)
            winner = winning_rounds.get(round_num, {})
            attacker_team = str(dmg.get("attackerTeamName", "") or "")
            if (
                is_enemy_damage
                and attacker_sid in rws_points
                and (
                    (winner.get("name") and attacker_team == winner.get("name"))
                    or (winner.get("side") and attacker_side == winner.get("side"))
                )
            ):
                round_damage = winning_round_damage.setdefault(round_num, {})
                round_damage[attacker_sid] = round_damage.get(attacker_sid, 0) + amount

    # Basic RWS: share 100 points between the winning side by damage in each won round.
    for round_damage in winning_round_damage.values():
        total_damage = sum(round_damage.values())
        if total_damage <= 0:
            continue
        for sid, amount in round_damage.items():
            rws_points[sid] += amount * 100.0 / total_damage

    # Build results
    results = []
    if not isinstance(players_data, dict):
        return results
    for steam_id, player in players_data.items():
        name = player.get("name", "")
        if not name:
            continue

        team_letter = (player.get("team") or {}).get("letter", "")
        team_name = ""
        if team_letter == "A":
            team_name = team_a.get("name", "")
        elif team_letter == "B":
            team_name = team_b.get("name", "")

        entry_kills = player.get("firstKillCount", 0)
        entry_deaths = player.get("firstDeathCount", 0)
        multi_kills = (
            player.get("twoKillCount", 0)
            + player.get("threeKillCount", 0)
            + player.get("fourKillCount", 0)
            + player.get("fiveKillCount", 0)
        )
        clutches_won = (
            player.get("oneVsOneWonCount", 0)
            + player.get("oneVsTwoWonCount", 0)
            + player.get("oneVsThreeWonCount", 0)
            + player.get("oneVsFourWonCount", 0)
            + player.get("oneVsFiveWonCount", 0)
        )

        from utils.stats_calc import calculate_impact

        impact = calculate_impact(
            entry_kills=entry_kills,
            entry_deaths=entry_deaths,
            multi_kills=multi_kills,
            clutches_won=clutches_won,
            rounds_played=rounds_count,
        )

        sk = side_kills.get(steam_id, {"T": 0, "CT": 0})
        sd = side_deaths.get(steam_id, {"T": 0, "CT": 0})
        sdm = side_damage.get(steam_id, {"T": 0, "CT": 0})
        sr = side_rounds.get(steam_id, {"T": 0, "CT": 0})

        t_rounds = max(sr["T"], 1)
        ct_rounds = max(sr["CT"], 1)
        t_k = sk["T"]
        ct_k = sk["CT"]
        t_d = sd["T"]
        ct_d = sd["CT"]

        t_adr_val = round(sdm["T"] / t_rounds, 1)
        ct_adr_val = round(sdm["CT"] / ct_rounds, 1)

        # Approximate T/CT rating from side-specific stats
        from utils.stats_calc import calculate_rating as _calc_rtg

        t_rating, _, _ = _calc_rtg(
            kills=t_k,
            deaths=t_d,
            rounds_played=t_rounds,
            adr=t_adr_val,
            kast=player.get("kast", 70),
            impact=0,
        )
        ct_rating, _, _ = _calc_rtg(
            kills=ct_k,
            deaths=ct_d,
            rounds_played=ct_rounds,
            adr=ct_adr_val,
            kast=player.get("kast", 70),
            impact=0,
        )

        results.append(
            {
                "steam_id": int(steam_id) if steam_id.isdigit() else steam_id,
                "name": name,
                "team_name": team_name,
                "team_letter": team_letter,
                "kills": player.get("killCount", 0),
                "deaths": player.get("deathCount", 0),
                "assists": player.get("assistCount", 0),
                "adr": round(player.get("averageDamagePerRound", 0), 1),
                "kpr": round(player.get("averageKillPerRound", 0), 2),
                "dpr": round(player.get("averageDeathPerRound", 0), 2),
                "kast": round(player.get("kast", 0), 1),
                "headshot_percentage": round(player.get("headshotPercent", 0), 1),
                "headshot_count": player.get("headshotCount", 0),
                "rating": round(player.get("hltvRating2", 0), 2),
                "impact": round(impact, 2),
                "mvp_count": player.get("mvpCount", 0),
                "first_kill_count": entry_kills,
                "first_death_count": entry_deaths,
                "clutches_won": clutches_won,
                # 多杀细分
                "multi1k": player.get("oneKillCount", 0),
                "multi2k": player.get("twoKillCount", 0),
                "multi3k": player.get("threeKillCount", 0),
                "multi4k": player.get("fourKillCount", 0),
                "multi5k": player.get("fiveKillCount", 0),
                # 投掷物统计
                "utility_damage": round(player.get("utilityDamage", 0), 1),
                "utility_damage_per_round": round(player.get("utilityDamagePerRound", 0), 2),
                "enemies_flashed": player.get("enemyFlashCount", 0),
                "flash_count": player.get("flashbangCount", 0),
                "he_count": player.get("heGrenadeCount", 0),
                "smoke_count": player.get("smokeCount", 0),
                "molotov_count": player.get("molotovCount", 0),
                # 交换击杀与目标相关数据
                "trade_kills": player.get("tradeKillCount", 0),
                "trade_deaths": player.get("tradeDeathCount", 0),
                "bomb_plants": player.get("bombPlantedCount", 0),
                "bomb_defuses": player.get("bombDefusedCount", 0),
                "rounds_played": rounds_count,
                "damage_delta_per_round": round(
                    (player.get("healthDamage", 0) - damage_received.get(steam_id, 0))
                    / rounds_count,
                    2,
                ),
                "rws_basic": round(rws_points.get(steam_id, 0) / rounds_count, 2),
                # T/CT 侧数据
                "t_rating": t_rating,
                "ct_rating": ct_rating,
                "t_kills": t_k,
                "ct_kills": ct_k,
                "t_deaths": t_d,
                "ct_deaths": ct_d,
                "t_adr": t_adr_val,
                "ct_adr": ct_adr_val,
            }
        )

    return results


def get_match_info(match_data):
    """提取比赛基本信息（含半场比分）"""
    team_a = match_data.get("teamA", {})
    team_b = match_data.get("teamB", {})

    rounds = match_data.get("rounds", [])
    if not isinstance(rounds, list):
        rounds = []

    halftime = _extract_halftime_scores(match_data)

    return {
        "map_name": match_data.get("mapName", ""),
        "date": match_data.get("date", ""),
        "duration_seconds": int(match_data.get("duration", 0) / 1_000_000_000)
        if match_data.get("duration")
        else 0,
        "team_a_name": (team_a or {}).get("name", ""),
        "team_b_name": (team_b or {}).get("name", ""),
        "team_a_score": (team_a or {}).get("score", 0),
        "team_b_score": (team_b or {}).get("score", 0),
        "rounds_count": len(rounds),
        "tick_rate": match_data.get("tickrate", 0),
        "source": match_data.get("source", ""),
        "halftime": halftime,
    }


def normalize_map_name(name):
    """标准化地图名称：去掉 de_/cs_ 前缀，统一小写"""
    n = name.lower().replace(" ", "_")
    for prefix in ("de_", "cs_"):
        if n.startswith(prefix):
            n = n[len(prefix) :]
            break
    return n


def match_map_slot(demo_map_name, match_map_names):
    """
    将 demo 中的地图名匹配到比赛的图槽

    参数:
        demo_map_name: demo 中解析出的地图名（如 'de_mirage'）
        match_map_names: list，比赛的三张图名（如 ['Mirage', None, None]）

    返回:
        int: 匹配到的 slot 索引 (0/1/2)，匹配不到返回 0
    """
    demo_norm = normalize_map_name(demo_map_name)
    for i, map_name in enumerate(match_map_names):
        if map_name and normalize_map_name(map_name) == demo_norm:
            return i
    # 未精确匹配，找第一个空槽
    for i, map_name in enumerate(match_map_names):
        if not map_name:
            return i
    return 0


def validate_demo(demo_path):
    """验证 Demo 文件格式"""
    if not os.path.exists(demo_path):
        return False, "文件不存在"
    if not demo_path.lower().endswith(".dem"):
        return False, "文件格式错误，需要 .dem 文件"
    return True, "文件有效"
