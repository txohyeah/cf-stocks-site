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

# 全部 19 张表
# ⚠️ 2026-09-16 补：原来漏了 6 张 macro_* 表。其中 macro_notes 是模型/人工写的
#    解读笔记 + 「当前宏观定性」历史，**丢了不可再生**（macro_calendar / macro_series /
#    macro_daily 还能从 stock-analytics sqlite 重灌，但笔记和人工定性不能）。
#    新增表时必须同步加到这里，否则备份静默漏表（本脚本不会报错）。
TABLES = [
    'users', 'sessions', 'articles', 'stocks', 'industries',
    'industry_lines', 'stock_modules', 'module_blocks',
    'tracking_rules', 'tracking_data', 'catalysts', 'pe_history',
    'risk_checks',
    'macro_calendar', 'macro_series', 'macro_daily',
    'macro_conditions', 'macro_industry_state', 'macro_notes',
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


def check_coverage(db):
    """防漏表守卫：D1 里的业务表必须都在 TABLES 里（2026-09-16 因漏 6 张 macro_* 而加）。

    D1/CF 自建的系统表（sqlite_sequence、_cf_KV）不算业务表，跳过。
    """
    ok, rows, _m, err = execute_sql(
        db, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    if not ok:
        return None, f'读表清单失败: {err}'
    have = {r['name'] for r in rows}
    skip = {'sqlite_sequence', '_cf_KV'}
    missing = sorted(have - set(TABLES) - skip)
    extra = sorted(set(TABLES) - have)
    return (missing, extra), None


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

    # 0. 防漏表守卫：业务表必须全部在 TABLES 里，漏了就拒绝备份（宁可报警不可静默漏）
    cov, cerr = check_coverage(db)
    if cerr:
        print(f"[WARN] 防漏表检查跳过：{cerr}")
    else:
        missing, extra = cov
        if missing:
            print(f"[FAIL] 以下 D1 业务表不在备份清单里（漏备份）: {missing}")
            print(f"[FIX] 把它们加进 scripts/backup_d1.py 的 TABLES 后重跑")
            sys.exit(1)
        if extra:
            print(f"[WARN] 清单里的这些表在 D1 上不存在（可能已改名/删除）: {extra}")
        print(f"[OK] 表覆盖检查通过：{len(TABLES)} 张表全部存在")

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