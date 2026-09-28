"""
给 templates/ 下所有 HTML 文件的 <img> 标签添加 loading="lazy" 属性。
用途：让图片延迟加载（用户滚动到附近才下载），加快首屏速度。

对于已经有 loading 属性的 img 标签会跳过。
"""

import os
import re
import sys


# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")


def add_lazy_to_img(content: str) -> tuple[str, int]:
    """
    给 HTML 内容中所有 <img> 标签添加 loading="lazy"。
    返回 (修改后的内容, 添加次数)。

    匹配规则：
      - 寻找 <img 开头...> 结束的标签
      - 如果标签内已有 loading= 属性，跳过
      - 否则在 <img 后面插入 loading="lazy"
    """
    added_count = 0
    # 匹配 <img 后面跟任意字符直到 > （非贪婪匹配，跨行）
    # <img 后可能跟各种属性，最后以 > 结束
    img_pattern = re.compile(
        r'<img\b([^>]*?)>',
        re.IGNORECASE | re.DOTALL
    )

    def replace_match(match):
        nonlocal added_count
        full_tag = match.group(0)   # 完整标签，如 <img src="...">
        attrs = match.group(1)      # 属性部分（不含 <img 和 >）

        # 跳过已经含有 loading= 的标签
        if re.search(r'\bloading\s*=', attrs, re.IGNORECASE):
            return full_tag

        # 跳过 XHTML 自闭合的（在模板中极少见，但保留兼容）
        # 在 <img 后面插入 loading="lazy"
        added_count += 1
        return '<img loading="lazy"' + match.group(1) + '>'

    new_content = img_pattern.sub(replace_match, content)
    return new_content, added_count


def process_file(filepath: str) -> int:
    """处理单个文件，返回添加了几处"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        print(f"  [错误] 无法读取: {e}", file=sys.stderr)
        return 0

    new_content, count = add_lazy_to_img(original)

    if count > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)

    return count


def main():
    total_files = 0
    total_added = 0

    print("=" * 50)
    print("  图片懒加载属性添加工具")
    print("=" * 50)

    for root, dirs, files in os.walk(TEMPLATES_DIR):
        for filename in files:
            if not filename.endswith(".html"):
                continue
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, TEMPLATES_DIR)

            added = process_file(filepath)
            if added > 0:
                print(f"  ✓ {rel_path} — 添加了 {added} 处")
                total_files += 1
                total_added += added

    print(f"\n共在 {total_files} 个文件中添加了 {total_added} 处 loading=\"lazy\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
