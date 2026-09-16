#!/usr/bin/env python3
"""增量回填 pe_history：从 stock-analytics daily_basic 拉 PE 历史灌入 D1。

用法：
  python3 scripts/backfill_pe.py --code 301165.SZ,300835.SZ   # 指定股票
  python3 scripts/backfill_pe.py --missing                     # 自动找 pe_history 为空的股票
  python3 scripts/backfill_pe.py --all                         # 全部 tracked 股票
  python3 scripts/backfill_pe.py --code 600519.SH --dry-run     # 只看要写多少行，不写

======================================================================
🛑 2026-09-16 安全改造（别改回去）
原实现对每只股票 `DELETE FROM pe_history WHERE stock_code=?` 后整只重插（每只 ~730 行）。
  1) 写额度：D1 免费版每日行写上限 100,000，**DELETE 也按删除行数计写**。
     `--all` 跑一遍 = 删 10 万 + 插 10 万 = 20 万行写 = 日额度 2 倍 → code 7500 整条失败。
  2) 顺带白干：绝大多数股票其实只差今天这一行（实测 145 只里 96 只只需写 1 行）。
现在：先读该股票在 D1 的现有行，只 UPSERT「缺的 + 值不同的」，一行不删（孤行无害）。
     需要旧的"先删后插"语义时用 --purge（会重新吃掉整只股票的写额度，慎用）。
======================================================================
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import find_db, execute_sql   # noqa: E402

STOCK_DB = '/home/application/stock-analytics/data/stock.db'
PE_DAYS = 730
BATCH = 400
TOL = 1e-6          # PE 值比较容差（吃掉浮点末位噪声）


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


def fetch_d1_rows(db, code):
    """读该股票在 D1 的现有 PE 行 → {交易日: PE}。只读。"""
    ok, rows, _m, err = execute_sql(
        db, f"SELECT trade_date, pe_ttm FROM pe_history WHERE stock_code='{code}'")
    if not ok:
        raise RuntimeError(f'{code}: 读 D1 现有行失败 {err}')
    return {r['trade_date']: r['pe_ttm'] for r in rows}


def upsert(db, code, dates):
    """把 [(date, pe), ...] 按批 UPSERT 进 D1。"""
    vals = [f"('{code}', '{d}', {v})" for d, v in dates]
    written = 0
    for i in range(0, len(vals), BATCH):
        chunk = vals[i:i + BATCH]
        sql = ("INSERT INTO pe_history (stock_code, trade_date, pe_ttm) VALUES\n" + ",\n".join(chunk) +
               " ON CONFLICT(stock_code, trade_date) DO UPDATE SET pe_ttm = excluded.pe_ttm;")
        ok, _r, _m, err = execute_sql(db, sql)
        if not ok:
            print(f'{code}: UPSERT 失败（第 {i} 行起）{err}')
            return written, False
        written += len(chunk)
    return written, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', help='逗号分隔的股票代码')
    ap.add_argument('--missing', action='store_true', help='自动找 pe_history 为空的股票')
    ap.add_argument('--all', action='store_true', help='全部 tracked 股票')
    ap.add_argument('--purge', action='store_true',
                    help='旧语义：先 DELETE 该股票全部 PE 行再整只重插（吃掉整只股票的写额度，慎用）')
    ap.add_argument('--dry-run', action='store_true', help='只统计要写多少行，不写 D1')
    args = ap.parse_args()

    db = find_db()
    if not db:
        raise SystemExit('D1 不存在')
    codes = load_codes_from_d1(db, 'all' if args.all else ('missing' if args.missing else ''), args.code)
    if not codes:
        print('没有需要回填的股票')
        return

    if args.purge:
        print(f'[WARN] --purge 会先 DELETE 每只股票的全部 PE 行再整只重插；'
              f'{len(codes)} 只 × ~{PE_DAYS} 行 ≈ {len(codes) * PE_DAYS * 2:,} 行写（含删除计写）。')

    conn = sqlite3.connect(STOCK_DB)
    cur = conn.cursor()
    total_new = total_upd = total_purged = 0
    skipped = 0
    for code in codes:
        rows = fetch_pe(cur, code)
        if not rows:
            print(f'{code}: 无 PE 数据（stock-analytics 无记录）')
            continue

        if args.purge:
            if args.dry_run:
                print(f'{code}: [DRY] purge 需 {len(rows)} 插 + 删除 {len(fetch_d1_rows(db, code))} 行')
                continue
            ok, _r, _m, err = execute_sql(db, f"DELETE FROM pe_history WHERE stock_code='{code}'")
            if not ok:
                print(f'{code}: DELETE 失败 {err}')
                continue
            total_purged += 1
            n, ok2 = upsert(db, code, rows)
            total_new += n
            print(f'{code}: purge 重灌 {n} 条')
            continue

        have = fetch_d1_rows(db, code)
        todo = [(d, v) for d, v in rows
                if d not in have or abs(float(have[d]) - float(v)) > TOL]
        n_new = sum(1 for d, _v in todo if d not in have)
        n_upd = len(todo) - n_new
        if not todo:
            skipped += 1
            print(f'{code}: 无需变更（D1 {len(have)} 行 / 本地 {len(rows)} 行）')
            continue
        if args.dry_run:
            print(f'{code}: [DRY] 需写 {len(todo)} 行（新增 {n_new} / 更新 {n_upd}；D1 现有 {len(have)}，本地 {len(rows)}）')
            total_new += n_new
            total_upd += n_upd
            continue
        n, ok2 = upsert(db, code, todo)
        total_new += n_new
        total_upd += n_upd
        print(f'{code}: 写入 {n} 行（新增 {n_new} / 更新 {n_upd}；D1 原有 {len(have)}）')
    conn.close()
    tag = '[DRY] ' if args.dry_run else ''
    print(f'{tag}完成：涉及 {len(codes)} 只，跳过 {skipped} 只（无需变更），'
          f'新增 {total_new} 行 / 更新 {total_upd} 行'
          + (f'，purge 重灌 {total_purged} 只' if total_purged else ''))


if __name__ == '__main__':
    main()
