"""敏感信息检查 — 扫描项目中疑似 API Key、密码、token 的泄露。用法: python secret_scan.py"""
import os
import re
import subprocess
import sys

# 项目根目录（脚本在 .claude/scripts/ 下，往上两级就是根目录）
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# 要跳过的目录（不扫描）
SKIP_DIRS = {".venv", ".git", "__pycache__", ".backups", "node_modules", ".claude/skills"}

# 要跳过的文件（环境变量文件本来就有密钥，不报）
SKIP_FILES = {".env", ".env.example", ".env.local"}

# 敏感信息匹配规则（正则表达式）
# 每组: (正则模式, 风险说明)
RULES = [
    # API Key 模式: sk- 开头 + 长字符串
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), "疑似 OpenAI/Claude API Key (sk-开头)"),
    # Bearer token: Bearer 后面跟长字符串
    (re.compile(r'Bearer\s+[A-Za-z0-9\-_\.]{20,}'), "Bearer Token"),
    # 密码赋值: password= 或 password: 或 password =
    (re.compile(r'(?i)password\s*[=:]\s*["\'][^"\']{4,}["\']'), "明文密码赋值"),
    # API Key 赋值: api_key= 或 api_key:
    (re.compile(r'(?i)api[_-]?key\s*[=:]\s*["\'][A-Za-z0-9\-_]{10,}["\']'), "API Key 硬编码"),
    # Token 赋值: token= 或 token:
    (re.compile(r'(?i)(?:access_)?token\s*[=:]\s*["\'][A-Za-z0-9\-_\.]{16,}["\']'), "Token 硬编码"),
    # Secret 赋值: secret= 或 secret:
    (re.compile(r'(?i)secret\s*[=:]\s*["\'][A-Za-z0-9\-_]{8,}["\']'), "Secret 硬编码"),
    # 数据库连接字符串（含密码）: mysql://user:password@ 或 postgresql://user:password@
    (re.compile(r'(?:mysql|postgres(?:ql)?|sqlite)://[^:]+:[^@]+@'), "数据库连接含明文密码"),
    # 私钥标记
    (re.compile(r'-----BEGIN (?:RSA|EC|DSA|OPENSSH) PRIVATE KEY-----'), "私钥文件内容"),
]

# git staged（已暂存）文件列表 —— 这些是高危，红色警告
def get_staged_files():
    """获取 git 暂存区中的文件列表"""
    try:
        result = subprocess.run(
            "git diff --cached --name-only",
            shell=True, capture_output=True, text=True,
            cwd=ROOT, timeout=10
        )
        return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()
    except Exception:
        return set()


def should_skip(filepath):
    """判断是否应该跳过该文件"""
    name = os.path.basename(filepath)
    if name in SKIP_FILES:
        return True
    # 检查路径中是否包含要跳过的目录
    parts = filepath.replace("\\", "/").split("/")
    for part in parts:
        if part in SKIP_DIRS:
            return True
    return False


def scan_file(filepath):
    """扫描单个文件，返回匹配列表 [(行号, 匹配文本, 规则说明)]"""
    findings = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return findings

    for line_no, line in enumerate(lines, 1):
        # 跳过注释行（但也不完全依赖，因为行内可能有注释外的内容）
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        for pattern, description in RULES:
            matches = pattern.findall(line)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                findings.append((line_no, match, description))

    return findings


def main():
    print("=" * 60)
    print("🔍 敏感信息扫描")
    print("=" * 60)

    staged = get_staged_files()
    if staged:
        print(f"\n⚠️  暂存区中有 {len(staged)} 个文件（这些如果泄露会标红）")

    total_files = 0
    total_findings = 0
    all_results = []  # [(文件路径, 是否staged, [(行号, 匹配, 说明)])]

    # 遍历项目所有文件
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # 跳过不需要扫描的目录
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, ROOT)

            if should_skip(rel_path):
                continue

            total_files += 1
            findings = scan_file(filepath)
            if findings:
                # 判断文件是否在暂存区
                is_staged = rel_path.replace("\\", "/") in staged
                all_results.append((rel_path, is_staged, findings))
                total_findings += len(findings)

    # 输出结果
    if not all_results:
        print(f"\n✅ 扫描了 {total_files} 个文件，未发现敏感信息泄露！")
        return 0

    print(f"\n📋 扫描了 {total_files} 个文件，发现 {total_findings} 处可疑敏感信息：\n")

    # 先输出暂存区的（红色警告）
    staged_results = [(p, s, f) for p, s, f in all_results if s]
    unstaged_results = [(p, s, f) for p, s, f in all_results if not s]

    if staged_results:
        print("⚠️  ===== 以下文件在 Git 暂存区中（高危！红色警告）=====\n")
        for rel_path, _, findings in staged_results:
            print(f"🔴 {rel_path}")
            for line_no, match, desc in findings:
                # 截断过长的匹配
                display = match[:80] + "..." if len(match) > 80 else match
                print(f"    第{line_no}行: {display}")
                print(f"            ({desc})")
            print()

    if unstaged_results:
        if staged_results:
            print("🟡 ===== 以下文件未暂存（仍需注意）=====\n")
        for rel_path, _, findings in unstaged_results:
            print(f"🟡 {rel_path}")
            for line_no, match, desc in findings:
                display = match[:80] + "..." if len(match) > 80 else match
                print(f"    第{line_no}行: {display}")
                print(f"            ({desc})")
            print()

    # 汇总
    staged_count = sum(len(f) for _, s, f in all_results if s)
    if staged_count > 0:
        print(f"\n🔴 暂存区共 {staged_count} 处敏感信息 — 强烈建议先移除再提交！")
        print("   用 git reset HEAD <文件> 可以把文件从暂存区移除")
    else:
        print(f"\n🟡 共 {total_findings} 处可疑信息（均未暂存）— 建议检查后删除或移入 .env")

    return 0


if __name__ == "__main__":
    sys.exit(main())
