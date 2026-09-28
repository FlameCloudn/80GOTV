"""一键重置开发环境 — 备份数据库 → 重建 → 重启Flask → 验证。用法: python dev_reset.py"""

import datetime
import os
import shutil
import subprocess
import sys

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS_DIR = os.path.join(ROOT, ".claude", "scripts")
BACKUP_DIR = os.path.join(ROOT, ".backups")
DB_FILE = os.path.join(ROOT, "cs_site.db")


def step(msg):
    """打印步骤标题"""
    print(f"\n{'─' * 50}")
    print(f"  {msg}")
    print(f"{'─' * 50}")


def run_script(script_name):
    """运行同目录下的脚本"""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"  ⚠️  脚本不存在: {script_name}，跳过")
        return False
    print(f"  运行: python {script_name}")
    result = subprocess.run(
        f'python "{script_path}"', shell=True, cwd=ROOT, capture_output=False, timeout=120
    )
    return result.returncode == 0


def backup_database():
    """备份当前数据库"""
    if not os.path.exists(DB_FILE):
        print("  数据库文件不存在，跳过备份")
        return True

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"cs_site_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    shutil.copy2(DB_FILE, backup_path)
    size_mb = os.path.getsize(DB_FILE) / 1024 / 1024
    print(f"  ✅ 已备份: {backup_name} ({size_mb:.1f} MB)")
    return True


def kill_flask():
    """停止所有 Flask 进程"""
    print("  正在停止 Flask...")
    try:
        # Windows: taskkill 杀掉 python 进程（比较粗暴，但在开发环境 OK）
        subprocess.run("taskkill /F /IM python.exe 2>NUL", shell=True, timeout=10)
        # 也尝试杀掉 pythonw
        subprocess.run("taskkill /F /IM pythonw.exe 2>NUL", shell=True, timeout=10)
        print("  ✅ Flask 已停止")
        return True
    except Exception as e:
        print(f"  ⚠️  停止失败: {e}（可能已经停了）")
        return True


def reset_database():
    """清空并重建数据库"""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("  ✅ 旧数据库已删除")

    # 运行初始化
    init_path = os.path.join(ROOT, "init_db.py")
    if os.path.exists(init_path):
        print("  正在初始化数据库...")
        result = subprocess.run(
            f'python "{init_path}"',
            shell=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print("  ✅ 数据库初始化完成")
            return True
        else:
            print(f"  ❌ 初始化失败: {result.stderr[:200]}")
            return False
    else:
        print("  ⚠️  init_db.py 不存在，跳过数据库初始化")
        return False


def start_flask():
    """后台启动 Flask"""
    print("  正在启动 Flask...")
    try:
        subprocess.Popen(
            f'python "{os.path.join(ROOT, "app.py")}"',
            shell=True,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("  ✅ Flask 已后台启动（端口 5000）")
        print("  等待 3 秒让服务就绪...")
        import time

        time.sleep(3)
        return True
    except Exception as e:
        print(f"  ❌ 启动失败: {e}")
        return False


def main():
    print("=" * 60)
    print("⚠️  一键重置开发环境")
    print("=" * 60)
    print()
    print("这将执行以下操作：")
    print("  1. 备份当前数据库到 .backups/")
    print("  2. 停止 Flask 服务")
    print("  3. 删除并重建数据库")
    print("  4. 重新启动 Flask")
    print("  5. 运行验证脚本")
    print()
    print("⚠️  数据库中的当前数据将被清空！")
    print()

    # 确认提示
    confirm = input("输入 yes 继续，其他任意键取消: ")
    if confirm != "yes":
        print("\n❌ 已取消")
        return 0

    # 步骤 1: 备份
    step("1/5 备份当前数据库")
    backup_database()

    # 步骤 2: 停止 Flask
    step("2/5 停止 Flask 服务")
    kill_flask()

    # 步骤 3: 重建数据库
    step("3/5 重建数据库")
    if not reset_database():
        print("\n❌ 数据库重建失败，终止流程。可以恢复备份：")
        print("   查看 .backups/ 目录下的备份文件")
        return 1

    # 步骤 4: 启动 Flask
    step("4/5 启动 Flask")
    start_flask()

    # 步骤 5: 验证
    step("5/5 运行验证脚本")
    verify_ok = run_script("verify_changes.py")

    # 结果汇总
    print(f"\n{'═' * 60}")
    if verify_ok:
        print("✅ 重置完成！开发环境已就绪。")
        print("   访问 http://127.0.0.1:5000 查看前台")
        print("   访问 http://127.0.0.1:5000/admin/login 管理后台")
    else:
        print("⚠️  重置基本完成，但验证脚本未全部通过。")
        print("   建议手动检查页面是否能正常打开")
    print(f"{'═' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
