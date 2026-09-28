"""静态资源体积 — 列出 static/ 下所有资源文件大小，按大小降序，标注大文件。用法: python asset_sizes.py"""
import os
import sys

# 项目根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATIC_DIR = os.path.join(ROOT, "static")

# 关心的文件类型
TARGET_EXTS = {".css", ".js", ".png", ".jpg", ".jpeg", ".woff2", ".woff", ".ttf", ".svg", ".gif", ".ico", ".webp"}

# 大文件阈值（字节）
BIG_THRESHOLD = 500 * 1024  # 500KB


def format_size(size_bytes):
    """把字节数转成可读格式"""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} B"


def get_file_type(ext):
    """根据扩展名分类"""
    type_map = {
        ".css": "样式",
        ".js": "脚本",
        ".png": "图片",
        ".jpg": "图片",
        ".jpeg": "图片",
        ".gif": "图片",
        ".webp": "图片",
        ".svg": "图标",
        ".ico": "图标",
        ".woff2": "字体",
        ".woff": "字体",
        ".ttf": "字体",
    }
    return type_map.get(ext, "其他")


def main():
    print("=" * 60)
    print("静态资源体积分析")
    print("=" * 60)

    if not os.path.exists(STATIC_DIR):
        print(f"❌ static/ 目录不存在: {STATIC_DIR}")
        return 1

    # 收集所有目标文件
    files_info = []
    for dirpath, dirnames, filenames in os.walk(STATIC_DIR):
        # 跳过 __pycache__
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in TARGET_EXTS:
                filepath = os.path.join(dirpath, filename)
                size = os.path.getsize(filepath)
                rel_path = os.path.relpath(filepath, ROOT)
                files_info.append((rel_path, size, ext))

    if not files_info:
        print("未找到静态资源文件")
        return 0

    # 按大小降序排列
    files_info.sort(key=lambda x: x[1], reverse=True)

    # 统计
    total_size = sum(s for _, s, _ in files_info)
    big_files = [(p, s) for p, s, _ in files_info if s >= BIG_THRESHOLD]

    # 分类统计
    type_stats = {}
    for _, size, ext in files_info:
        ftype = get_file_type(ext)
        type_stats[ftype] = type_stats.get(ftype, 0) + size

    print(f"\n📊 文件总数: {len(files_info)}")
    print(f"📦 总大小: {format_size(total_size)}")
    print(f"\n分类统计:")
    for ftype in ["样式", "脚本", "图片", "字体", "图标", "其他"]:
        if ftype in type_stats:
            print(f"  {ftype}: {format_size(type_stats[ftype])}")

    # 列出所有文件（按大小降序）
    print(f"\n{'─' * 60}")
    print(f"{'文件路径':<50} {'大小':>10} {'类型'}")
    print(f"{'─' * 60}")

    for rel_path, size, ext in files_info:
        ftype = get_file_type(ext)
        size_str = format_size(size)
        flag = " ⚠️ 大文件" if size >= BIG_THRESHOLD else ""
        # 截断过长的路径
        display_path = rel_path if len(rel_path) <= 48 else "..." + rel_path[-45:]
        print(f"{display_path:<50} {size_str:>10} {ftype}{flag}")

    # 大文件警告
    if big_files:
        print(f"\n{'═' * 60}")
        print(f"⚠️  超过 500KB 的文件（{len(big_files)} 个）— 可能拖慢页面加载速度：")
        for path, size in big_files:
            print(f"  📦 {format_size(size):>10}  {path}")
        print(f"\n💡 优化建议：")
        print("  - 图片: 压缩或转 WebP 格式")
        print("  - 字体: 用 font-display:swap 避免阻塞渲染")
        print("  - JS/CSS: 开启 gzip 压缩或使用 CDN")
    else:
        print(f"\n✅ 没有超过 500KB 的文件，资源体积健康！")

    return 0


if __name__ == "__main__":
    sys.exit(main())
