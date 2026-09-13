#!/usr/bin/env python3
"""增量回填 pe_history：从 stock-analytics daily_basic 拉 PE 历史灌入 D1。

用法：
  python3 scripts/backfill_pe.py --code 301165.SZ,300835.SZ   # 指定股票
  python3 scripts/backfill_pe.py --missing                     # 自动找 pe_history 为空的股票
  python3 scripts/backfill_pe.py --all                         # 全量（幂等，先删后插）
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import find_db, execute_sql

STOCK_DB = '/home/application/stock-analytics/data/stock.db'
PE_DAYS = 730
BATCH = 400


def load_codes_from_d1(db, mode, explicit):
    if explicit:
        return [c.strip() for c in explicit.split(',') if c.strip()]
    if mode == 'all':
        ok, rows, _m, _e = execute_sql(db, "SELECT code FROM stocks WHERE tracked=1")
        return [r['code'] for r in rows] if ok else []
    # --missing：pe_history 为空的股票
    ok, rows, _m, _e = execute_sql(db, (
        "SELECT s.code FROM stocks s WHERE s.tracked=1 "
        "AND NOT EXISTS (SELECT 1 FROM pe_history p WHERE p.stock_code=s.code)"))
    return [r['code'] for r in rows] if ok else []


def fetch_pe(cur, code):
    cur.execute(
        'SELECT trade_date, pe_ttm FROM daily_basic WHERE ts_code=? AND pe_ttm IS NOT NULL '
        'ORDER BY trade_date DESC LIMIT ?', (code, PE_DAYS))
    rows = cur.fetchall()
    rows.reverse()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', help='逗号分隔的股票代码')
    ap.add_argument('--missing', action='store_true', help='自动找 pe_history 为空的股票')
    ap.add_argument('--all', action='store_true', help='全量回填（幂等）')
    args = ap.parse_args()

    db = find_db()
    if not db:
        raise SystemExit('D1 不存在')
    codes = load_codes_from_d1(db, 'all' if args.all else ('missing' if args.missing else ''), args.code)
    if not codes:
        print('没有需要回填的股票')
        return

    conn = sqlite3.connect(STOCK_DB)
    cur = conn.cursor()
    total = 0
    for code in codes:
        rows = fetch_pe(cur, code)
        if not rows:
            print(f'{code}: 无 PE 数据（stock-analytics 无记录）')
            continue
        # 幂等：先删该股旧数据再插
        ok, _r, _m, err = execute_sql(db, f"DELETE FROM pe_history WHERE stock_code='{code}'")
        if not ok:
            print(f'{code}: DELETE 失败 {err}')
            continue
        vals = [f"('{code}', '{d}', {v})" for d, v in rows]
        for i in range(0, len(vals), BATCH):
            chunk = vals[i:i + BATCH]
            sql = "INSERT INTO pe_history (stock_code, trade_date, pe_ttm) VALUES\n" + ",\n".join(chunk) + ";"
            ok, _r, _m, err = execute_sql(db, sql)
            if not ok:
                print(f'{code}: INSERT 失败（{i} 起）{err}')
                break
        else:
            total += len(rows)
            print(f'{code}: 回填 {len(rows)} 条 PE 历史')
    conn.close()
    print(f'完成，共回填 {total} 条')


if __name__ == '__main__':
    main()