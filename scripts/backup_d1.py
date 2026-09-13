#!/usr/bin/env python3
"""备份 D1 关键表为 INSERT SQL 存档（seed 恢复用）。"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import execute_sql, find_db

TABLES = ['stocks', 'industry_lines', 'stock_modules', 'module_blocks', 'tracking_rules']

def esc(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"

def main():
    db = find_db()
    out = []
    out.append(f"-- D1 backup {datetime.datetime.now().isoformat()}")
    for t in TABLES:
        ok, rows, meta, err = execute_sql(db, f"SELECT * FROM {t}")
        if not ok:
            print(f"[FAIL] {t}: {err}", file=sys.stderr)
            sys.exit(1)
        cols = list(meta.get('columns', [])) if meta else []
        if not cols and rows:
            cols = list(rows[0].keys())
        out.append(f"-- table {t} ({len(rows)} rows)")
        for r in rows:
            vals = ', '.join(esc(r.get(c)) for c in cols)
            out.append(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({vals});")
    path = sys.argv[1] if len(sys.argv) > 1 else 'data/seed_backup_20260903.sql'
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')
    print(f"backup written: {path} ({len(out)} lines)")

if __name__ == '__main__':
    import os
    main()