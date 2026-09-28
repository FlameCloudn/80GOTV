"""查询 Kimi API 余额。用法: python check_balance.py"""

import json
import os
import subprocess
import sys

# 读 API Key
KIMI_KEY = os.environ.get("KIMI_API_KEY", "")
if not KIMI_KEY:
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("KIMI_API_KEY="):
                    KIMI_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break


def check_balance():
    """返回 (总额, 现金, 赠金, 是否低余额)"""
    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "https://api.moonshot.cn/v1/users/me/balance",
                "-H",
                f"Authorization: Bearer {KIMI_KEY}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        data = json.loads(result.stdout)
        if data.get("status") and "data" in data:
            d = data["data"]
            total = d.get("available_balance", 0)
            cash = d.get("cash_balance", 0)
            voucher = d.get("voucher_balance", 0)
            low = total < 10  # 低于 10 元视为不足
            return total, cash, voucher, low
        return None, None, None, False
    except Exception:
        return None, None, None, False


if __name__ == "__main__":
    total, cash, voucher, low = check_balance()

    if total is None:
        print("❌ 无法查询余额（网络问题或 API Key 错误）")
        sys.exit(1)

    status = "🔴 余额不足！" if low else "🟢 充足"
    print(f"{status}")
    print(f"  总额: {total:.2f} 元")
    print(f"  现金: {cash:.2f} 元")
    print(f"  赠金: {voucher:.2f} 元")

    if low:
        print("\n⚠️ 余额低于 10 元，建议充值: https://platform.kimi.com")
        sys.exit(2)
    else:
        print("  💡 低于 10 元时会提醒")
