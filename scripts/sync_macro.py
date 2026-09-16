#!/usr/bin/env python3
"""宏观数据同步：stock-analytics sqlite → 线上 D1（宏观页 /macro 的数据源）。

用法：
  python3 scripts/sync_macro.py                        # 只生成 SQL 到 data/macro_sync.sql
  python3 scripts/sync_macro.py --exec                 # 生成并写入 D1（日频仅近 30 天）
  python3 scripts/sync_macro.py --exec --daily-full    # 首次上线：日频全量灌历史

三张表（DDL 见 schema.sql）：
  macro_calendar  数据发布日历（含未来排期）——**全量 UPSERT**（约 2.9k 行，规模小、语义最稳）
  macro_series    月度/季度序列（社融/货币/物价/GDP）——全量 UPSERT
  macro_daily     日频（Shibor 隔夜/两融余额/北向净买）——默认近 30 天，--daily-full 才全量

为什么日频默认只同步近 30 天：全量约 9.3k 行 ≈ 47 次 D1 API 调用，每天重灌没必要；
首启用一次 --daily-full 灌满历史，之后日常增量即可。

数据来源（均为 tushare，经 stock-analytics 落库，口径与坑见 stock-analytics/specs/macro-data.md）：
  macro_calendar ← eco_cal（实际/预期/上月 + 解析后的 surprise）
  macro_series   ← sf_month / cn_m / cn_cpi / cn_ppi / cn_gdp
  macro_daily    ← shibor / margin / moneyflow_hsgt
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import STOCK_ANALYTICS_DB  # noqa: E402  （本机私有路径，不入版本控制）

OUT = os.path.join(ROOT, 'data', 'macro_sync.sql')
BATCH = 100  # D1 单条语句有长度上限（SQLITE_TOOBIG），分批
DAILY_LOOKBACK_DAYS = 30

CAL_COLS = ['date', 'time', 'event', 'value', 'fore_value', 'pre_value',
            'value_num', 'fore_num', 'pre_num', 'surprise', 'unit']
SERIES_COLS = ['month', 'indicator', 'value', 'unit']
DAILY_COLS = ['trade_date', 'indicator', 'value', 'unit']


def q(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return repr(float(v)) if isinstance(v, float) else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def connect():
    if not os.path.isfile(STOCK_ANALYTICS_DB):
        raise SystemExit(f'找不到 stock-analytics 数据库：{STOCK_ANALYTICS_DB}')
    return sqlite3.connect(f'file:{STOCK_ANALYTICS_DB}?mode=ro', uri=True)


def calendar_rows(conn):
    sql = f"SELECT {', '.join(CAL_COLS)} FROM macro_calendar ORDER BY date, time, event"
    return list(conn.execute(sql))


def series_rows(conn):
    """把 5 张月度序列表拍成 (month, indicator, value, unit) 长表。

    指标命名保持中文可读，页面直接显示；单位随指标固定。
    """
    out = []
    for month, inc, stock in conn.execute(
            'SELECT month, inc_month, stk_endval FROM sf_month ORDER BY month'):
        if inc is not None:
            out.append((month, '社融增量', float(inc), '亿元'))
        if stock is not None:
            out.append((month, '社融存量', float(stock), '万亿元'))
    for month, m1, m2 in conn.execute('SELECT month, m1_yoy, m2_yoy FROM cn_m ORDER BY month'):
        if m1 is not None:
            out.append((month, 'M1同比', float(m1), '%'))
        if m2 is not None:
            out.append((month, 'M2同比', float(m2), '%'))
        if m1 is not None and m2 is not None:
            out.append((month, 'M1M2剪刀差', float(m1) - float(m2), '百分点'))
    for month, cpi in conn.execute('SELECT month, nt_yoy FROM cn_cpi ORDER BY month'):
        if cpi is not None:
            out.append((month, 'CPI同比', float(cpi), '%'))
    for month, ppi in conn.execute('SELECT month, ppi_yoy FROM cn_ppi ORDER BY month'):
        if ppi is not None:
            out.append((month, 'PPI同比', float(ppi), '%'))
    for quarter, gdp in conn.execute('SELECT quarter, gdp_yoy FROM cn_gdp ORDER BY quarter'):
        if gdp is not None:
            out.append((quarter, 'GDP同比', float(gdp), '%'))
    return out


def daily_rows(conn, since):
    """日频三指标 → (trade_date, indicator, value, unit)。

    单位统一成页面好读的口径：Shibor 隔夜 %、两融余额 亿元、北向净买 亿元。
    """
    out = []
    for date, on in conn.execute('SELECT date, "on" FROM shibor WHERE date >= ? ORDER BY date', (since,)):
        if on is not None:
            out.append((date, 'Shibor隔夜', float(on), '%'))
    for date, ye in conn.execute(
            'SELECT trade_date, SUM(rzye + rqye) / 1e8 FROM margin WHERE trade_date >= ? '
            'GROUP BY trade_date ORDER BY trade_date', (since,)):
        if ye is not None:
            out.append((date, '两融余额', float(ye), '亿元'))
    for date, nm in conn.execute(
            'SELECT trade_date, north_money / 1e4 FROM moneyflow_hsgt WHERE trade_date >= ? ORDER BY trade_date',
            (since,)):
        if nm is not None:
            out.append((date, '北向净买', float(nm), '亿元'))
    return out


def insert_stmts(table, cols, rows, conflict_cols):
    """生成分批 INSERT ... ON CONFLICT DO UPDATE（幂等；表内不 DELETE，避免半途失败露空窗）。"""
    if not rows:
        return []
    upd = [c for c in cols if c not in conflict_cols]
    tail = ('\nON CONFLICT(' + ', '.join(conflict_cols) + ') DO UPDATE SET\n  '
            + ',\n  '.join(f'{c} = excluded.{c}' for c in upd) + ';')
    stmts = []
    for i in range(0, len(rows), BATCH):
        vals = ',\n'.join('(' + ', '.join(q(v) for v in r) + ')' for r in rows[i:i + BATCH])
        stmts.append(f'INSERT INTO {table} ({", ".join(cols)}) VALUES\n{vals}{tail}')
    return stmts


def exec_stmts(stmts):
    import cf_d1
    db = cf_d1.find_db()
    if not db:
        raise SystemExit('D1 不存在')
    total = 0
    for i, stmt in enumerate(stmts, 1):
        ok, _rows, meta, err = cf_d1.execute_sql(db, stmt)
        if not ok:
            raise SystemExit(f'[FAIL] 语句 {i}: ' + json.dumps(err, ensure_ascii=False)[:400])
        n = meta.get('rows_changed', 0)
        total += n
        print(f'[OK] 语句 {i} rows_changed={n}')
    return db, total


def verify(db):
    """回读核对（D1 的 upsert 语句 meta.rows_changed 恒为 0，不能凭它判断写入成功）。"""
    import cf_d1
    checks = [
        ('macro_calendar 总行数/最新发布日',
         'SELECT COUNT(*) n, MAX(date) latest FROM macro_calendar WHERE value IS NOT NULL'),
        ('macro_calendar 未来排期行数',
         "SELECT COUNT(*) n, MIN(date) first_date FROM macro_calendar WHERE value IS NULL AND date > strftime('%Y%m%d','now','+8 hours')"),
        ('macro_series 指标数与最新月份',
         'SELECT COUNT(DISTINCT indicator) n, MAX(month) latest FROM macro_series'),
        ('macro_daily 指标数与最新日期',
         'SELECT COUNT(DISTINCT indicator) n, MAX(trade_date) latest FROM macro_daily'),
    ]
    for label, sql in checks:
        ok, rows, _m, err = cf_d1.execute_sql(db, sql)
        if not ok:
            print(f'[核对FAIL] {label}: ' + json.dumps(err, ensure_ascii=False)[:200])
            continue
        print(f'[核对] {label}: {json.dumps(rows[0] if rows else None, ensure_ascii=False)}')


def main():
    ap = argparse.ArgumentParser(description='宏观数据同步 → D1')
    ap.add_argument('--exec', action='store_true', help='写入 D1（默认只生成 SQL）')
    ap.add_argument('--daily-full', action='store_true', help='日频全量（首次上线用；默认近 30 天）')
    ap.add_argument('--out', default=OUT, help=f'SQL 输出路径（默认 {OUT}）')
    args = ap.parse_args()

    since = '00000000' if args.daily_full else (datetime.now() - timedelta(days=DAILY_LOOKBACK_DAYS)).strftime('%Y%m%d')
    conn = connect()
    cal = calendar_rows(conn)
    series = series_rows(conn)
    daily = daily_rows(conn, since)
    conn.close()

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    header = [f'-- 宏观数据（sync_macro.py 生成 {now}）',
              '-- 源：stock-analytics macro_calendar/macro_series/macro_daily（tushare）']
    stmts = []
    stmts += insert_stmts('macro_calendar', CAL_COLS, cal, ['date', 'time', 'event'])
    stmts += insert_stmts('macro_series', SERIES_COLS, series, ['month', 'indicator'])
    stmts += insert_stmts('macro_daily', DAILY_COLS, daily, ['trade_date', 'indicator'])

    # 注释块放在文件头且**不单独成句**（否则 cf_d1 exec 会把注释当语句执行）
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(header) + '\n' + ';\n'.join(stmts) + ';\n')
    print(f'SQL 已写出：{args.out}（{len(stmts)} 条语句）')
    print(f'  日历 {len(cal)} 行（其中未来排期 {sum(1 for r in cal if r[0] > now[:10].replace("-", ""))} 行）'
          f' ｜ 序列 {len(series)} 行 ｜ 日频 {len(daily)} 行（since={since}）')

    if args.exec:
        db, total = exec_stmts(stmts)
        print(f'已写入 D1，累计 rows_changed={total}（⚠️ D1 对 upsert 恒回报 0，以回读为准）')
        verify(db)


if __name__ == '__main__':
    main()
