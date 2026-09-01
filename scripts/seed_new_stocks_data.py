#!/usr/bin/env python3
"""补录 300802/300811 的 pe_history + tracking_data（增量，不 DELETE 全表）
用法：python3 scripts/seed_new_stocks_data.py
"""
import sqlite3
import os

import paths

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # projects/stocks-site
ANALYTICS_DB = paths.STOCK_ANALYTICS_DB
OUT = os.path.join(ROOT, 'data', 'seed_new_stocks_data.sql')

CODES = ['300802.SZ', '300811.SZ']
PE_DAYS = 730

def q(s):
    return str(s).replace("'", "''")

def main():
    cur = sqlite3.connect(ANALYTICS_DB)

    # ---------- pe_history ----------
    pe_rows = []
    for code in CODES:
        rows = cur.execute(
            "SELECT trade_date, pe_ttm FROM daily_basic "
            "WHERE ts_code=? AND pe_ttm IS NOT NULL ORDER BY trade_date DESC LIMIT ?",
            (code, PE_DAYS)).fetchall()
        for d, v in rows:
            pe_rows.append(f"('{q(code)}', '{d}', {v})")
    stmts = ["-- 增量 pe_history（300802/300811）"]
    for i in range(0, len(pe_rows), 800):
        chunk = pe_rows[i:i+800]
        stmts.append("INSERT INTO pe_history (stock_code, trade_date, pe_ttm) VALUES\n" + ",\n".join(chunk) + ";")
    print(f"pe_history: {len(pe_rows)} 行")

    # ---------- tracking_data（最新 9 维）----------
    td_rows = []
    for code in CODES:
        l = cur.execute(
            "SELECT trade_date, close, pe, pe_ttm, pb, dv_ratio, total_mv, circ_mv, turnover_rate, volume_ratio "
            "FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", (code,)).fetchone()
        if not l:
            continue
        date = l[0]
        dims = [
            ('close', l[1]), ('pe_lyr', l[2]), ('pe_ttm', l[3]), ('pb', l[4]),
            ('dv_ratio', l[5]), ('total_mv', l[6]), ('circ_mv', l[7]),
            ('turnover_rate', l[8]), ('volume_ratio', l[9]),
        ]
        for dim, val in dims:
            if val is None:
                continue
            td_rows.append(f"('{q(code)}', '{dim}', '{val}', '{date}')")
    stmts.append("-- 增量 tracking_data（300802/300811）")
    for i in range(0, len(td_rows), 800):
        chunk = td_rows[i:i+800]
        stmts.append("INSERT INTO tracking_data (stock_code, dimension, value, as_of) VALUES\n" + ",\n".join(chunk) + ";")
    print(f"tracking_data: {len(td_rows)} 行")

    with open(OUT, 'w') as f:
        f.write("\n".join(stmts) + "\n")
    print(f"写入 {OUT}")

if __name__ == '__main__':
    main()