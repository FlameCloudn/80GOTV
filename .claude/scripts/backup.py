"""一键备份：数据库 + 头像 + 配置文件。用法: python backup.py [--restore 备份文件名]"""
import sys, os, shutil, zipfile, datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKUP_DIR = os.path.join(ROOT, ".backups")

def backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"backup_{timestamp}.zip"
    zip_path = os.path.join(BACKUP_DIR, zip_name)

    print("打包中…")

    items = []
    # 数据库
    db_path = os.path.join(ROOT, "cs_site.db")
    if os.path.exists(db_path):
        items.append(("cs_site.db", db_path))
        print(f"  ✅ 数据库 ({os.path.getsize(db_path)/1024/1024:.1f}MB)")

    # 头像
    avatars_dir = os.path.join(ROOT, "static", "avatars")
    if os.path.exists(avatars_dir):
        for f in os.listdir(avatars_dir):
            items.append((f"avatars/{f}", os.path.join(avatars_dir, f)))
        print(f"  ✅ 头像 ({len(os.listdir(avatars_dir))} 个)")

    # 配置文件
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        items.append((".env", env_path))
        print("  ✅ .env 配置")

    # 压缩
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, filepath in items:
            zf.write(filepath, arcname)

    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print(f"\n📦 备份完成: {zip_name} ({size_mb:.1f}MB)")

    # 清理旧备份，只保留最近 10 个
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")])
    if len(backups) > 10:
        for old in backups[:-10]:
            os.remove(os.path.join(BACKUP_DIR, old))
            print(f"  🗑️  清理旧备份: {old}")

def restore(filename):
    zip_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(zip_path):
        print(f"❌ 备份文件不存在: {filename}")
        print(f"   可用备份: {', '.join(f for f in os.listdir(BACKUP_DIR) if f.endswith('.zip'))}")
        sys.exit(1)

    print(f"⚠️  即将恢复 {filename}，当前数据会被覆盖！")
    confirm = input("确认？(输入 yes 继续): ")
    if confirm != "yes":
        print("已取消")
        return

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(ROOT)
    print(f"✅ 恢复完成: {filename}")

if __name__ == "__main__":
    if "--restore" in sys.argv:
        idx = sys.argv.index("--restore")
        name = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if not name:
            print("用法: python backup.py --restore backup_20260615.zip")
            sys.exit(1)
        restore(name)
    else:
        backup()
