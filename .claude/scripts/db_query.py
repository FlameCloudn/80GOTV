"""数据库查询工具。用法: python db_query.py "SELECT * FROM players LIMIT 5" """

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models import get_db


def query(sql, params=None):
    """执行查询，返回 [(列名列表), [行数据], ...]"""
    conn = get_db()
    try:
        cur = conn.execute(sql, params or ())
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, rows
    finally:
        conn.close()


def query_json(sql, params=None):
    """返回 JSON 格式"""
    cols, rows = query(sql, params)
    results = []
    for row in rows:
        results.append(dict(zip(cols, row)))
    return results


def print_table(cols, rows):
    """简单表格输出"""
    if not rows:
        print("(空)")
        return

    # 计算列宽
    widths = [len(c) for c in cols]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    # 表头
    header = " | ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("-" * len(header))

    # 数据行
    for row in rows:
        print(" | ".join(str(v)[:w].ljust(w) for v, w in zip(row, widths)))

    print(f"\n共 {len(rows)} 条")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('用法: python db_query.py "SQL语句"')
        print('示例: python db_query.py "SELECT id,name FROM teams"')
        print("     python db_query.py --tables  (列出所有表)")
        print("     python db_query.py --schema teams  (查看表结构)")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--tables":
        cols, rows = query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for (name,) in rows:
            print(name)
    elif arg == "--schema":
        table = sys.argv[2] if len(sys.argv) > 2 else None
        if not table:
            print("请指定表名，如: python db_query.py --schema players")
            sys.exit(1)
        cols, rows = query(f"PRAGMA table_info({table})")
        # cid, name, type, notnull, dflt_value, pk
        print(f"表 {table}:")
        for row in rows:
            cid, name, coltype, notnull, default, pk = row
            flags = []
            if pk:
                flags.append("PRIMARY KEY")
            if notnull:
                flags.append("NOT NULL")
            print(f"  {name}  {coltype}  {' '.join(flags)}")
    elif arg == "--json":
        sql = sys.argv[2] if len(sys.argv) > 2 else "SELECT 1"
        print(json.dumps(query_json(sql), ensure_ascii=False, indent=2))
    else:
        cols, rows = query(arg)
        print_table(cols, rows)
