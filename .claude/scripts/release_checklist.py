"""发布检查清单 — 依次运行所有检查脚本，综合判断是否可以发布。用法: python release_checklist.py"""

import os
import subprocess
import sys

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS_DIR = os.path.join(ROOT, ".claude", "scripts")

# 要运行的检查项: (脚本名, 检查说明, 是否必须通过)
CHECKS = [
    ("verify_changes.py", "页面可用性检查（10个页面能否打开）", True),
    ("env_check.py", "环境变量检查（SECRET_KEY等必需项）", True),
    ("check_uncommitted.py", "未提交文件检查（是否有遗漏提交）", False),
    ("secret_scan.py", "敏感信息扫描（是否有密钥泄露）", True),
]


def run_check(script_name, description):
    """运行一个检查脚本，返回 (通过?, 输出摘要)"""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        return None, f"脚本不存在: {script_name}"

    try:
        result = subprocess.run(
            f'python "{script_path}"',
            shell=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        passed = result.returncode == 0
        output = result.stdout.strip()
        if not output:
            output = result.stderr.strip()

        # 截取输出摘要（最后 5 行）
        lines = output.split("\n")
        summary = "\n".join(lines[-5:]) if len(lines) > 5 else output

        return passed, summary
    except subprocess.TimeoutExpired:
        return False, "执行超时（超过 60 秒）"
    except Exception as e:
        return False, f"执行出错: {e}"


def main():
    print("=" * 60)
    print("🚀 发布检查清单")
    print("=" * 60)

    results = []
    must_pass_failed = 0
    optional_failed = 0

    for i, (script, desc, required) in enumerate(CHECKS, 1):
        print(f"\n{'─' * 50}")
        print(f"  [{i}/{len(CHECKS)}] {desc}")
        print(f"  运行: python {script}")
        print(f"{'─' * 50}")

        passed, summary = run_check(script, desc)

        if passed is None:
            icon = "⚪"
            status = "跳过（脚本不存在）"
        elif passed:
            icon = "✅"
            status = "通过"
        else:
            icon = "❌"
            status = "未通过"
            if required:
                must_pass_failed += 1
            else:
                optional_failed += 1

        print(f"  {icon} {status}")

        if summary and not passed:
            print(f"  {'─' * 40}")
            for line in summary.split("\n"):
                print(f"  {line}")

        results.append((script, passed, required, status))

    # 综合判断
    print(f"\n{'═' * 60}")
    print("📊 综合结果")
    print(f"{'═' * 60}")

    total = len(CHECKS)
    passed_count = sum(1 for _, p, _, _ in results if p is True)

    print(f"\n  检查通过: {passed_count}/{total}")

    # 汇总表格
    print(f"\n  {'检查项':<25} {'结果':<15} {'要求'}")
    print(f"  {'─' * 50}")
    for script, passed, required, status in results:
        req_text = "必须" if required else "建议"
        icon = "✅" if passed else ("❌" if passed is False else "⚪")
        print(f"  {script:<25} {icon} {status:<10} {req_text}")

    # 最终判断
    print(f"\n{'═' * 60}")
    if must_pass_failed == 0:
        print("✅ 所有必须项已通过 — 可以发布！")
    else:
        print(f"❌ 有 {must_pass_failed} 个必须项未通过 — 发布前需要处理")

    if optional_failed > 0:
        print(f"💡 还有 {optional_failed} 个建议项未通过（非阻塞，但建议处理）")

    return 0 if must_pass_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
