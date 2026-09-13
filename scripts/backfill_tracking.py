#!/usr/bin/env python3
"""回填 tracking_data（9 维最新行情指标）：从 stock-analytics daily_basic 拉最新行灌入 D1。

用法：
  python3 scripts/backfill_tracking.py --code 301165.SZ,300835.SZ   # 指定股票
  python3 scripts/backfill_tracking.py --missing                     # 自动找 tracking_data 为空的股票
  python3 scripts/backfill_tracking.py --all                         # 全量（幂等，先删后插）
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import find_db, execute_sql

STOCK_DB = '/home/application/stock-analytics/data/stock.db'
DIMS = ['trade_date', 'close', 'pe', 'pe_ttm', 'pb', 'dv_ratio', 'total_mv', 'circ_mv', 'turnover_rate', 'volume_ratio']
# D1 tracking_data 只存 9 个指标维度（trade_date 作为 as_of）
MAP = [
    ('close', 'trade_date'), ('pe_ttm', 'trade_date'), ('pe_lyr', None),
    ('pb', 'trade_date'), ('dv_ratio', 'trade_date'), ('total_mv', 'trade_date'),
    ('circ_mv', 'trade_date'), ('turnover_rate', 'trade_date'), ('volume_ratio', 'trade_date'),
]


def load_codes_from_d1(db, mode, explicit):
    if explicit:
        return [c.strip() for c in explicit.split(',') if c.strip()]
    if mode == 'all':
        ok, rows, _m, _e = execute_sql(db, "SELECT code FROM stocks WHERE tracked=1")
        return [r['code'] for r in rows] if ok else []
    ok, rows, _m, _e = execute_sql(db, (
        "SELECT s.code FROM stocks s WHERE s.tracked=1 "
        "AND NOT EXISTS (SELECT 1 FROM tracking_data t WHERE t.stock_code=s.code)"))
    return [r['code'] for r in rows] if ok else []


def fetch_latest(cur, code):
    """返回最新一行的 dict；pe_lyr 用 daily_basic 的 pe 字段映射。"""
    cur.execute(
        'SELECT trade_date, close, pe, pe_ttm, pb, dv_ratio, total_mv, circ_mv, turnover_rate, volume_ratio '
        'FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1', (code,))
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip(['trade_date', 'close', 'pe', 'pe_ttm', 'pb', 'dv_ratio', 'total_mv', 'circ_mv', 'turnover_rate', 'volume_ratio'], row))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', help='逗号分隔的股票代码')
    ap.add_argument('--missing', action='store_true', help='自动找 tracking_data 为空的股票')
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
        row = fetch_latest(cur, code)
        if not row:
            print(f'{code}: 无行情数据（stock-analytics 无记录）')
            continue
        # 幂等：先删该股旧数据再插
        ok, _r, _m, err = execute_sql(db, f"DELETE FROM tracking_data WHERE stock_code='{code}'")
        if not ok:
            print(f'{code}: DELETE 失败 {err}')
            continue
        as_of = row['trade_date']
        items = [
            f"('{code}', 'close', '{row['close']}', '{as_of}')",
            f"('{code}', 'pe_ttm', '{row['pe_ttm']}', '{as_of}')",
            f"('{code}', 'pe_lyr', '{row['pe']}', '{as_of}')",
            f"('{code}', 'pb', '{row['pb']}', '{as_of}')",
            f"('{code}', 'dv_ratio', '{row['dv_ratio']}', '{as_of}')",
            f"('{code}', 'total_mv', '{row['total_mv']}', '{as_of}')",
            f"('{code}', 'circ_mv', '{row['circ_mv']}', '{as_of}')",
            f"('{code}', 'turnover_rate', '{row['turnover_rate']}', '{as_of}')",
            f"('{code}', 'volume_ratio', '{row['volume_ratio']}', '{as_of}')",
        ]
        sql = "INSERT INTO tracking_data (stock_code, dimension, value, as_of) VALUES\n" + ",\n".join(items) + ";"
        ok, _r, _m, err = execute_sql(db, sql)
        if not ok:
            print(f'{code}: INSERT 失败 {err}')
            continue
        total += len(items)
        print(f'{code}: 回填 {len(items)} 维行情（{as_of}）')
    conn.close()
    print(f'完成，共回填 {total} 条')


if __name__ == '__main__':
    main()