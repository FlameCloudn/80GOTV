"""日志分析器 — 分析 flask.log 中的错误趋势和重复错误。用法: python log_analyzer.py"""
import os
import sys
import re
from collections import Counter

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_FILE = os.path.join(ROOT, "logs", "flask.log")


def parse_log(log_path):
    """解析日志文件，返回 (错误列表, 时间分布, 错误文本列表)"""
    if not os.path.exists(log_path):
        return [], {}, []

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    errors = []  # [(时间, 级别, 内容)]
    error_texts = []  # 用于统计重复

    # 匹配时间戳和日志级别
    # Flask 日志格式通常: [2024-01-01 12:00:00,000] ERROR in xxx: message
    time_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}):\d{2}')

    for line in lines:
        # 判断日志级别
        level = None
        if "[ERROR]" in line or "ERROR in" in line or " ERROR " in line:
            level = "ERROR"
        elif "[CRITICAL]" in line or "CRITICAL in" in line:
            level = "CRITICAL"
        elif "[WARNING]" in line or "WARNING in" in line or " WARNING " in line:
            level = "WARNING"
        else:
            continue

        # 提取时间
        time_match = time_pattern.search(line)
        hour = time_match.group(1) if time_match else "未知时间"

        # 清理内容（去掉时间戳和模块信息，保留核心消息）
        content = line.strip()
        # 尝试提取更简洁的错误消息
        clean = re.sub(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d+', '', content)
        clean = re.sub(r'\[(ERROR|WARNING|CRITICAL)\]', '', clean)
        clean = clean.strip()

        errors.append((hour, level, clean))
        error_texts.append(clean)

    # 按小时分组
    hour_dist = Counter()
    for hour, _, _ in errors:
        hour_dist[hour] += 1

    return errors, dict(hour_dist.most_common()), error_texts


def main():
    print("=" * 60)
    print("📋 日志分析 — flask.log")
    print("=" * 60)

    if not os.path.exists(LOG_FILE):
        print(f"\n❌ 日志文件不存在: {LOG_FILE}")
        print("   Flask 启动过吗？启动后会在 logs/flask.log 生成日志")
        return 1

    # 文件大小
    size_mb = os.path.getsize(LOG_FILE) / 1024 / 1024
    print(f"\n📄 日志文件大小: {size_mb:.1f} MB")

    errors, hour_dist, error_texts = parse_log(LOG_FILE)

    if not errors:
        print("✅ 日志中没有发现 ERROR、WARNING 或 CRITICAL 级别的记录")
        return 0

    # 1. 统计各类型错误数量
    level_counts = Counter(level for _, level, _ in errors)
    print(f"\n📊 错误类型统计:")
    for level in ["CRITICAL", "ERROR", "WARNING"]:
        count = level_counts.get(level, 0)
        icon = "🔴" if level == "CRITICAL" else ("🟠" if level == "ERROR" else "🟡")
        print(f"  {icon} {level}: {count} 条")

    # 2. 按小时分组
    if hour_dist:
        print(f"\n⏰ 按小时分布（显示前 12 小时）:")
        for hour, count in list(hour_dist.items())[:12]:
            bar = "█" * min(count, 30)  # 柱状图，最多 30 个字符
            print(f"  {hour}:00  {bar} {count}")

    # 3. 重复最多的 3 条错误
    error_counter = Counter(error_texts)
    top_errors = error_counter.most_common(3)
    if top_errors:
        print(f"\n🔁 重复最多的 3 条错误:")
        for i, (msg, count) in enumerate(top_errors, 1):
            # 截断长消息
            display = msg[:120] + "..." if len(msg) > 120 else msg
            print(f"  {i}. (出现 {count} 次) {display}")

    print(f"\n{'─' * 60}")
    print(f"共 {len(errors)} 条错误/警告记录")

    return 0


if __name__ == "__main__":
    sys.exit(main())
