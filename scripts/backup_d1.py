#!/usr/bin/env python3
"""D1 全量备份：导出全部表为 INSERT SQL → 本地验证 → 滚动保留最近 N 份。

用法：
  python3 scripts/backup_d1.py            # 默认保留 3 份
  python3 scripts/backup_d1.py --keep 5   # 指定保留份数

验证逻辑：
  1) INSERT 条数统计 == D1 线上行数（必须通过，否则不删旧备份）
  2) 恢复演练：用 schema.sql 建内存库 + 导入备份 SQL（尽力而为，失败仅警告）
"""
import os
import sys
import glob
import argparse
import datetime
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import execute_sql, find_db

# 全部 13 张表
TABLES = [
    'users', 'sessions', 'articles', 'stocks', 'industries',
    'industry_lines', 'stock_modules', 'module_blocks',
    'tracking_rules', 'tracking_data', 'catalysts', 'pe_history',
    'risk_checks',
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # projects/stocks-site
BACKUP_DIR = os.path.join(ROOT, 'data', 'backup')
SCHEMA_PATH = os.path.join(ROOT, 'schema.sql')


def esc(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def fetch_table(db, t):
    """从 D1 拉全表，返回 (cols, rows)。"""
    ok, rows, meta, err = execute_sql(db, f"SELECT * FROM {t}")
    if not ok:
        raise RuntimeError(f"{t}: {err}")
    cols = list(meta.get('columns', [])) if meta else []
    if not cols and rows:
        cols = list(rows[0].keys())
    return cols, rows


def write_sql(path, db):
    """导出全表为 INSERT SQL，返回 {表: 行数}。"""
    counts = {}
    lines = [f"-- D1 full backup {datetime.datetime.now().isoformat()}"]
    for t in TABLES:
        cols, rows = fetch_table(db, t)
        counts[t] = len(rows)
        lines.append(f"-- table {t} ({len(rows)} rows)")
        for r in rows:
            vals = ', '.join(esc(r.get(c)) for c in cols)
            lines.append(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({vals});")
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return counts


def count_inserts(path):
    """统计备份 SQL 中每张表的 INSERT 条数（不依赖 schema，可靠）。"""
    counts = {}
    with open(path) as f:
        for line in f:
            if line.startswith('INSERT INTO '):
                t = line.split()[2].split('(')[0]
                counts[t] = counts.get(t, 0) + 1
    return counts


def restore_check(path):
    """恢复演练：schema.sql 建内存库 + 导入备份 SQL。返回 (ok, msg)。"""
    try:
        conn = sqlite3.connect(':memory:')
        cur = conn.cursor()
        with open(SCHEMA_PATH) as f:
            cur.executescript(f.read())
        with open(path) as f:
            cur.executescript(f.read())
        conn.close()
        return True, '恢复演练通过（schema.sql 建库 + 导入成功）'
    except Exception as e:
        return False, f'恢复演练失败: {e}'


def rotate(keep):
    """滚动保留最近 keep 份，删除更旧的。返回删除列表。"""
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, 'd1_full_*.sql')))
    removed = []
    while len(files) > keep:
        f = files.pop(0)
        os.remove(f)
        removed.append(f)
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', type=int, default=3, help='滚动保留份数（默认 3）')
    args = ap.parse_args()

    os.makedirs(BACKUP_DIR, exist_ok=True)
    db = find_db()

    # 1. 导出
    today = datetime.datetime.now().strftime('%Y%m%d')
    path = os.path.join(BACKUP_DIR, f'd1_full_{today}.sql')
    counts = write_sql(path, db)
    total = sum(counts.values())
    print(f"[OK] 导出完成: {path}（{total} 行）")
    for t, n in counts.items():
        print(f"  {t}: {n} 行")

    # 2. 验证：INSERT 条数 == D1 行数
    inserts = count_inserts(path)
    mismatches = [t for t in counts if inserts.get(t, 0) != counts[t]]
    if mismatches:
        print(f"[FAIL] 验证失败，INSERT 条数与 D1 不一致: {mismatches}")
        print("[WARN] 保留全部旧备份，请人工检查")
        sys.exit(1)
    print(f"[OK] 验证通过：{len(counts)} 张表 INSERT 条数全部一致")

    # 3. 恢复演练（尽力而为）
    ok, msg = restore_check(path)
    print(f"[{'OK' if ok else 'WARN'}] {msg}")

    # 4. 滚动保留
    removed = rotate(args.keep)
    for f in removed:
        print(f"[DEL] 删除旧备份: {f}")
    print(f"[DONE] 保留最近 {args.keep} 份")


if __name__ == '__main__':
    main()