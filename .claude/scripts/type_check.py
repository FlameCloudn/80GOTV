"""类型检查：跑 pyright 检查项目 Python 代码。用法: python type_check.py"""
import sys, os, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)

result = subprocess.run(
    ["pyright", "."],
    capture_output=True, text=True, timeout=120
)

# 只显示最后几行（摘要）
lines = result.stdout.strip().split("\n")
for line in lines[-15:]:
    print(line)

if result.returncode == 0:
    print("\n0 errors")
    sys.exit(0)
else:
    error_count = sum(1 for l in lines if "error" in l.lower())
    warn_count = sum(1 for l in lines if "warning" in l.lower())
    print(f"\n{error_count} errors, {warn_count} warnings")
    sys.exit(1)
