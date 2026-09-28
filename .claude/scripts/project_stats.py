"""项目指标看板 —— 统计代码、数据库、测试概况。"""
import os
import sys
from collections import Counter

# 把项目根目录加入搜索路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)


def count_files_and_lines(extensions, exclude_dirs=None):
    """统计指定后缀的文件数和总行数，跳过排除目录。"""
    if exclude_dirs is None:
        exclude_dirs = {'.venv', '__pycache__', 'node_modules', '.backups', '.git', '.claude'}
    file_count = 0
    line_count = 0
    for root, dirs, files in os.walk(BASE_DIR):
        # 跳过排除目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in extensions:
                file_count += 1
                path = os.path.join(root, f)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                        line_count += sum(1 for _ in fh)
                except Exception:
                    pass
    return file_count, line_count


def count_tests():
    """统计测试函数/方法数量。"""
    test_count = 0
    # 搜索 _test.py 或 test_ 开头的文件
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in {'.venv', '__pycache__', 'node_modules', '.backups', '.git'}]
        for f in files:
            if f.endswith('_test.py') or f.startswith('test_'):
                path = os.path.join(root, f)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                        for line in fh:
                            stripped = line.strip()
                            if stripped.startswith('def test_') or stripped.startswith('async def test_'):
                                test_count += 1
                            elif stripped.startswith('class Test') or stripped.startswith('class Test_'):
                                test_count += 1
                except Exception:
                    pass
    return test_count


def count_db_tables_and_records():
    """统计数据库表数和记录数。"""
    table_count = 0
    record_count = 0
    try:
        from models import get_db
        conn = get_db()
        # 获取所有表名
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        table_count = len(tables)
        # 统计每个表的记录数
        for (table_name,) in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()
                record_count += row[0]
            except Exception:
                pass
        conn.close()
    except Exception as e:
        print(f"[警告] 无法连接数据库: {e}")
    return table_count, record_count


def main():
    # 统计前端代码
    html_files, html_lines = count_files_and_lines({'.html'})
    css_files, css_lines = count_files_and_lines({'.css'})
    js_files, js_lines = count_files_and_lines({'.js'})
    # 统计后端代码
    py_files, py_lines = count_files_and_lines({'.py'})

    total_files = html_files + css_files + js_files + py_files
    total_lines = html_lines + css_lines + js_lines + py_lines

    # 数据库统计
    table_count, record_count = count_db_tables_and_records()

    # 测试统计
    test_count = count_tests()

    # 输出详情
    print(f"{'类型':<12} {'文件数':>6} {'行数':>8}")
    print("-" * 28)
    print(f"{'Python':<12} {py_files:>6} {py_lines:>8}")
    print(f"{'HTML':<12} {html_files:>6} {html_lines:>8}")
    print(f"{'CSS':<12} {css_files:>6} {css_lines:>8}")
    print(f"{'JavaScript':<12} {js_files:>6} {js_lines:>8}")
    print("-" * 28)
    print(f"{'合计':<12} {total_files:>6} {total_lines:>8}")
    print()
    print(f"数据库: {table_count} 个表, {record_count} 条记录")
    print(f"测试: {test_count} 个")

    # 一句话摘要
    print()
    print(f"=== 项目摘要: {total_files} 个文件共 {total_lines} 行代码, "
          f"{table_count} 个数据库表({record_count} 条记录), {test_count} 个测试 ===")


if __name__ == '__main__':
    main()
