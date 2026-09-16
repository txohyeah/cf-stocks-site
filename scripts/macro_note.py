#!/usr/bin/env python3
"""宏观解读笔记：判断"今天该不该写" + 把写好的笔记落到 D1（宏观页 /macro 的解读层）。

页面分两层：
  自动判定层 —— macro_conditions 体检卡，每天由 sync_macro.py 刷新（规则生成，永不陈旧）
  解读笔记层 —— macro_notes 表，由本脚本写入（模型/人工撰写，带时间戳）

用法：
  python3 scripts/macro_note.py check                 # 人看的简报
  python3 scripts/macro_note.py check --json          # 给 agent cron 判断用（机读）
  python3 scripts/macro_note.py save --date 20260916 --title "..." \
      --body-file /tmp/note.md [--kind release] [--source agent]

为什么要有 check：cron 每天跑一次，但**大多数日子没有数据发布**——
按"有发布才写"（约 8~12 次/月）比每天硬写省事且不产废话。
check 返回 has_release=false 时，agent 应当直接结束、不写笔记。
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import STOCK_ANALYTICS_DB  # noqa: E402

import sync_macro as sm  # noqa: E402  （复用参照系/单位口径，避免两套算法）

# 写笔记时值得参考的市场价/资金面（都在 analytics 库内）
MARKET_DAILY = ['布伦特原油', 'WTI原油', '美债10Y', '美债2Y', '离岸人民币', 'Shibor隔夜', '两融余额', '北向净买']
LOOKBACK_DAYS = 3      # "新发布"回看窗口（发布日当天没跑成功，隔天补写）


def fmt_value(v, unit):
    if v is None:
        return '—'
    if unit == 'B':
        return f'{v / 1e12:.2f} 万亿'
    if unit == 'T':
        return f'{v / 1e12:.2f} 万亿'
    if unit == 'M':
        return f'{v / 1e6:.0f} 百万'
    if unit == '%':
        return f'{v:.2f}%'
    return f'{v:,.2f}{unit}'


def connect_ro():
    if not os.path.isfile(STOCK_ANALYTICS_DB):
        raise SystemExit(f'找不到 stock-analytics 数据库：{STOCK_ANALYTICS_DB}')
    return sqlite3.connect(f'file:{STOCK_ANALYTICS_DB}?mode=ro', uri=True)


def collect(today):
    """汇总：最近一次发布批（近 LOOKBACK_DAYS 天）+ 参照系 + 市场价 + 体检卡状态。"""
    conn = connect_ro()
    rows = list(conn.execute(
        f"SELECT {', '.join(sm.BASE_CAL_COLS)} FROM macro_calendar ORDER BY date, time, event"))
    refs = sm.derive_refs(rows)
    since = (datetime.strptime(today, '%Y%m%d') - timedelta(days=LOOKBACK_DAYS)).strftime('%Y%m%d')

    released = []
    for r in rows:
        date, time_, event, value, fore, pre, vnum, fnum, pnum, surprise, unit = r[:11]
        if vnum is None or date < since:
            continue
        rf = refs.get((r[0], r[1], r[2])) or (None,) * 7
        released.append({
            'date': date, 'time': time_, 'event': event,
            'value_text': value, 'fore_text': fore,
            'value': vnum, 'fore': fnum, 'surprise': surprise, 'unit': unit,
            'value_human': fmt_value(vnum, unit), 'fore_human': fmt_value(fnum, unit),
            'surprise_human': fmt_value(surprise, unit) if unit != '%' else (
                None if surprise is None else f'{surprise:+.2f} 个百分点'),
            'pct_rank': rf[5], 'pct_rank_n': rf[6],
            'ref_yoy_human': fmt_value(rf[0], unit), 'ref_yoy_pct': rf[2], 'ref_yoy_diff': rf[1],
            'ref_avg5_human': fmt_value(rf[3], unit),
        })
    released.sort(key=lambda x: (x['date'], x['time']))

    # 市场价：各取最新一条（两融按亿元合计，北向按日）
    market = {}
    for name in MARKET_DAILY:
        if name == '两融余额':
            v = conn.execute('SELECT trade_date, SUM(rzye + rqye) / 1e8 FROM margin '
                             'GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1').fetchone()
        elif name == '北向净买':
            v = conn.execute('SELECT trade_date, north_money / 1e4 FROM moneyflow_hsgt '
                             'ORDER BY trade_date DESC LIMIT 1').fetchone()
        elif name in ('布伦特原油', 'WTI原油'):
            sym = 'BRENT' if name == '布伦特原油' else 'WTI'
            v = conn.execute('SELECT date, close FROM oil_global WHERE symbol = ? '
                             'ORDER BY date DESC LIMIT 1', (sym,)).fetchone()
        elif name in ('美债10Y', '美债2Y'):
            col = 'y10' if name == '美债10Y' else 'y2'
            v = conn.execute(f'SELECT date, {col} FROM us_tycr ORDER BY date DESC LIMIT 1').fetchone()
        elif name == '离岸人民币':
            v = conn.execute('SELECT trade_date, bid_close FROM fx_daily '
                             'ORDER BY trade_date DESC LIMIT 1').fetchone()
        else:
            v = conn.execute('SELECT date, "on" FROM shibor ORDER BY date DESC LIMIT 1').fetchone()
        if v:
            market[name] = {'date': v[0], 'value': v[1]}

    # 月度序列最新（M1/M2/CPI/PPI 同比，供写笔记时引用）
    series = {}
    for ind, sql in (('M1同比', 'SELECT month, m1_yoy FROM cn_m ORDER BY month DESC LIMIT 1'),
                     ('M2同比', 'SELECT month, m2_yoy FROM cn_m ORDER BY month DESC LIMIT 1'),
                     ('CPI同比', 'SELECT month, nt_yoy FROM cn_cpi ORDER BY month DESC LIMIT 1'),
                     ('PPI同比', 'SELECT month, ppi_yoy FROM cn_ppi ORDER BY month DESC LIMIT 1'),
                     ('社融存量同比', 'SELECT month, stk_endval FROM sf_month ORDER BY month DESC LIMIT 1')):
        v = conn.execute(sql).fetchone()
        if v:
            series[ind] = {'month': v[0], 'value': v[1]}
    conn.close()

    return {'today': today, 'since': since, 'released': released,
            'market': market, 'series': series,
            'release_dates': sorted({x['date'] for x in released})}


def existing_notes(dates=None):
    """已写过的笔记（避免重复写；D1 读）"""
    import cf_d1
    db = cf_d1.find_db()
    sql = 'SELECT note_date, kind, created_at, title FROM macro_notes ORDER BY note_date DESC LIMIT 10'
    ok, rows, _m, err = cf_d1.execute_sql(db, sql)
    if not ok:
        return []
    return rows


def cmd_check(args):
    data = collect(args.today)
    notes = existing_notes()
    data['recent_notes'] = notes
    data['has_release'] = bool(data['released'])
    data['note_dates'] = sorted({n['note_date'] for n in notes})
    # 某次发布算"已写"，只要存在一篇写在**发布日当天或之后**的笔记（那篇必然是在看到数据之后写的）。
    # 只看 note_date 是否等于发布日会漏：笔记往往记在"这批数据的整理日"，与发布日本身错开一天。
    data['pending_dates'] = [d for d in data['release_dates']
                             if not any(n >= d for n in data['note_dates'])]
    data['should_write'] = bool(data['pending_dates'])
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return
    print(f"今天 {data['today']}｜回看窗口自 {data['since']}")
    print(f"窗口内发布 {len(data['released'])} 条，涉及日期 {data['release_dates']}")
    for x in data['released']:
        rank = '—' if x['pct_rank'] is None else f"{x['pct_rank'] * 100:.0f}%（第 {round(x['pct_rank'] * x['pct_rank_n'])}/{x['pct_rank_n']} 小）"
        print(f"  {x['date']} {x['event']}: {x['value_human']}（预期 {x['fore_human']}，差 {x['surprise_human']}）"
              f"｜分位 {rank}｜去年同期 {x['ref_yoy_human']}｜5 年同期均值 {x['ref_avg5_human']}")
    print(f"已写笔记日期 {data['note_dates'] or '无'}｜待写 {data['pending_dates'] or '无'} → should_write={data['should_write']}")
    print('市场：' + '｜'.join(f"{k} {v['value']:.2f}（{v['date']}）" for k, v in data['market'].items()))


def cmd_save(args):
    import cf_d1
    body = args.body
    if args.body_file:
        with open(args.body_file, encoding='utf-8') as f:
            body = f.read()
    if not body or not body.strip():
        raise SystemExit('笔记正文为空，拒绝写入')
    created = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    as_of = args.as_of or datetime.now().strftime('%Y%m%d')
    db = cf_d1.find_db()
    sql = (
        'INSERT INTO macro_notes (note_date, kind, created_at, title, body_md, covered, as_of, source) VALUES ('
        f"{sm.q(args.date)}, {sm.q(args.kind)}, {sm.q(created)}, {sm.q(args.title)}, {sm.q(body)}, "
        f"{sm.q(args.covered)}, {sm.q(as_of)}, {sm.q(args.source)})\n"
        'ON CONFLICT(note_date, kind) DO UPDATE SET\n'
        '  created_at = excluded.created_at, title = excluded.title, body_md = excluded.body_md,\n'
        '  covered = excluded.covered, as_of = excluded.as_of, source = excluded.source;')
    ok, _rows, _meta, err = cf_d1.execute_sql(db, sql)
    if not ok:
        raise SystemExit('[FAIL] 写入失败：' + json.dumps(err, ensure_ascii=False)[:400])
    # 回读核对（D1 upsert 恒回报 rows_changed=0，只能靠回读）
    ok, rows, _m, err = cf_d1.execute_sql(
        db, f"SELECT note_date, kind, created_at, title, LENGTH(body_md) n FROM macro_notes "
            f"WHERE note_date = {sm.q(args.date)} AND kind = {sm.q(args.kind)}")
    print('[核对] ' + json.dumps(rows[0] if rows else None, ensure_ascii=False))
    print('全部笔记：' + json.dumps(existing_notes(), ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description='宏观解读笔记（check / save）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    c = sub.add_parser('check', help='今天有没有新发布、该不该写笔记')
    c.add_argument('--today', default=datetime.now().strftime('%Y%m%d'))
    c.add_argument('--json', action='store_true')
    c.set_defaults(func=cmd_check)

    s = sub.add_parser('save', help='把笔记写入 D1 macro_notes')
    s.add_argument('--date', required=True, help='归属日期 YYYYMMDD（发布日）')
    s.add_argument('--kind', default='release', choices=['release', 'weekly'])
    s.add_argument('--title', default='')
    s.add_argument('--body', default='')
    s.add_argument('--body-file', default='')
    s.add_argument('--covered', default='', help='覆盖的事件名（逗号分隔）')
    s.add_argument('--as-of', default='')
    s.add_argument('--source', default='agent', choices=['agent', 'human'])
    s.set_defaults(func=cmd_save)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
