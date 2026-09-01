#!/usr/bin/env python3
"""stocks 站点详情数据导出管线 v2
输入：
  - media/u4_site_archive/api_stocks.json       → industry_lines（含 lineCat）
  - media/u4_site_archive/api_industries.json   → tracking_rules（行业红绿灯规则）
  - stock-analytics/data/stock.db               → pe_history（近730交易日）/ tracking_data（头部9维）/ 财务模块（income+fina_indicator+cashflow）
输出：
  - projects/stocks-site/data/detail_seed.sql
用法：
  python3 scripts/export_site.py
  python3 scripts/cf_d1.py exec ../data/detail_seed.sql
"""
import json
import os
import sqlite3

import paths

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # projects/stocks-site
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))                       # workspaces/default
ARCHIVE = os.path.join(WORKSPACE, 'media', 'u4_site_archive')
ANALYTICS_DB = paths.STOCK_ANALYTICS_DB
OUT = os.path.join(ROOT, 'data', 'detail_seed.sql')

PE_DAYS = 730             # PE 历史天数（stock-analytics 有 3 年数据）
INSERT_BATCH = 800        # 每条 INSERT 的 VALUES 行数（~80KB/条，D1 body 上限内）
FIN_PERIODS = ['20241231', '20251231', '20260331', '20260630']   # 财务表列：2024/2025/2026Q1/2026H1
FIN_LABELS = ['2024', '2025', '2026Q1', '2026H1']


def q(s):
    return str(s).replace("'", "''")


def load_stocks():
    with open(os.path.join(ARCHIVE, 'api_stocks.json')) as f:
        return json.load(f)


def load_industries():
    with open(os.path.join(ARCHIVE, 'api_industries.json')) as f:
        return json.load(f)


def build_industry_lines():
    items = load_stocks()
    rows = []
    for s in items:
        for i, r in enumerate(s.get('industryRoles') or []):
            rows.append(
                f"('{q(s['code'])}', '{q(r.get('id', ''))}', '{q(r.get('position', ''))}', "
                f"'{q(r.get('weight', ''))}', '{q(r.get('lineCat', ''))}', "
                f"'{q(r.get('segment', ''))}', '{q(r.get('note', ''))}', {i})")
    return (["-- industry_lines",
             "DELETE FROM industry_lines;",
             "INSERT INTO industry_lines (stock_code, line_id, position, weight, lineCat, segment, note, sort_order) VALUES\n" +
             ",\n".join(rows) + ";"], len(rows))


def build_tracking_rules():
    """行业红绿灯规则：股票按其产业线合并 industries.trackIndicators"""
    items = load_stocks()
    inds = load_industries()
    ind_rules = {x['id']: (x.get('trackIndicators') or []) for x in inds}
    stmts = ["-- tracking_rules（行业级红绿灯规则）", "DELETE FROM tracking_rules;"]
    rows = []
    for s in items:
        seen = set()
        order = 0
        for r in s.get('industryRoles') or []:
            for rule in ind_rules.get(r.get('id'), []):
                key = (rule.get('indicator') or '')
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append(
                    f"('{q(s['code'])}', '{q(key)}', '{q(key)}', '{q(rule.get('red', ''))}', "
                    f"'{q(rule.get('yellow', ''))}', '{q(rule.get('green', ''))}', {order})")
            order += 1
    for i in range(0, len(rows), INSERT_BATCH):
        chunk = rows[i:i + INSERT_BATCH]
        stmts.append(
            "INSERT INTO tracking_rules (stock_code, dimension, indicator, red, yellow, green, sort_order) VALUES\n" +
            ",\n".join(chunk) + ";")
    return stmts, len(rows)


def fetch_per_stock(cur):
    """返回 {code: {'pe': [...], 'latest': {...9维}}}"""
    stocks = load_stocks()
    out = {}
    for s in stocks:
        code = s['code']
        cur.execute('SELECT trade_date, pe_ttm FROM daily_basic WHERE ts_code=? AND pe_ttm IS NOT NULL '
                    'ORDER BY trade_date DESC LIMIT ?', (code, PE_DAYS))
        rows = cur.fetchall()
        if not rows:
            continue
        rows.reverse()
        cur.execute(
            'SELECT trade_date, close, pe, pe_ttm, pb, dv_ratio, total_mv, circ_mv, turnover_rate, volume_ratio '
            'FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1', (code,))
        lr = cur.fetchone()
        out[code] = {
            'pe': [(d, v) for d, v in rows],
            'latest': dict(zip(
                ['trade_date', 'close', 'pe', 'pe_ttm', 'pb', 'dv_ratio', 'total_mv', 'circ_mv', 'turnover_rate', 'volume_ratio'],
                lr))
        }
    return out


def build_pe_history(per):
    all_rows = []
    for code, info in per.items():
        for d, v in info['pe']:
            all_rows.append(f"('{q(code)}', '{d}', {v})")
    stmts = ["-- pe_history", "DELETE FROM pe_history;"]
    for i in range(0, len(all_rows), INSERT_BATCH):
        chunk = all_rows[i:i + INSERT_BATCH]
        stmts.append("INSERT INTO pe_history (stock_code, trade_date, pe_ttm) VALUES\n" + ",\n".join(chunk) + ";")
    return stmts, len(all_rows)


def build_tracking_data(per):
    rows = []
    for code, info in per.items():
        l = info['latest']
        if l is None:
            continue
        dims = [
            ('close', l['close']), ('pe_lyr', l['pe']), ('pe_ttm', l['pe_ttm']), ('pb', l['pb']),
            ('dv_ratio', l['dv_ratio']), ('total_mv', l['total_mv']), ('circ_mv', l['circ_mv']),
            ('turnover_rate', l['turnover_rate']), ('volume_ratio', l['volume_ratio']),
        ]
        for dim, val in dims:
            if val is None:
                continue
            rows.append(f"('{q(code)}', '{dim}', '{val}', '{l['trade_date']}')")
    stmts = ["-- tracking_data", "DELETE FROM tracking_data;"]
    for i in range(0, len(rows), INSERT_BATCH):
        chunk = rows[i:i + INSERT_BATCH]
        stmts.append("INSERT INTO tracking_data (stock_code, dimension, value, as_of) VALUES\n" + ",\n".join(chunk) + ";")
    return stmts, len(rows)


def build_finance_modules(cur):
    """关键财务数据模块：归母净利/EPS/ROE/营收/经营现金流 × 4 期"""
    stocks = load_stocks()
    stmts = ["-- 财务模块（stock_modules + module_blocks）",
             "DELETE FROM module_blocks;", "DELETE FROM stock_modules;"]
    n = 0
    placeholders = ','.join('?' * len(FIN_PERIODS))
    for s in stocks:
        code = s['code']
        income = {r[0]: r for r in cur.execute(
            f"SELECT end_date, n_income_attr_p, basic_eps, total_revenue FROM income "
            f"WHERE ts_code=? AND report_type='1' AND end_date IN ({placeholders})", (code, *FIN_PERIODS))}
        if not income:
            continue
        roe = {r[0]: r[1] for r in cur.execute(
            f"SELECT end_date, roe FROM fina_indicator WHERE ts_code=? AND end_date IN ({placeholders})",
            (code, *FIN_PERIODS))}
        cash = {r[0]: r[1] for r in cur.execute(
            f"SELECT end_date, n_cashflow_act FROM cashflow WHERE ts_code=? AND report_type='1' AND end_date IN ({placeholders})",
            (code, *FIN_PERIODS))}

        def cell(period, val):
            if val is None:
                return '—'
            v = val / 1e8 if isinstance(val, (int, float)) and abs(val) > 1e6 else val
            return f"{v:.1f}亿" if isinstance(v, float) and abs(v) >= 100 else f"{v:.2f}亿"

        rows = []
        rows.append(['归母净利润'] + [cell(p, income[p][1]) if p in income else '—' for p in FIN_PERIODS])
        rows.append(['EPS'] + [f"{income[p][2]:.2f}" if p in income and income[p][2] is not None else '—' for p in FIN_PERIODS])
        rows.append(['ROE(%)'] + [f"{roe[p]:.1f}" if p in roe and roe[p] is not None else '—' for p in FIN_PERIODS])
        rows.append(['营收'] + [cell(p, income[p][3]) if p in income else '—' for p in FIN_PERIODS])
        rows.append(['经营现金流'] + [cell(p, cash[p]) if p in cash else '—' for p in FIN_PERIODS])

        data = json.dumps({'headers': ['指标'] + FIN_LABELS, 'rows': rows}, ensure_ascii=False)
        stmts.append(
            f"INSERT INTO stock_modules (stock_code, module_key, title, template_key, sort_order, visible) VALUES "
            f"('{q(code)}', 'finance', '关键财务数据', 'finance', 1, 1);")
        stmts.append(
            f"INSERT INTO module_blocks (module_id, block_type, data_json, sort_order) VALUES "
            f"(last_insert_rowid(), 'table', '{q(data)}', 0);")
        n += 1
    return stmts, n


def main():
    parts = ["-- stocks 站点 P2 详情种子 v2（export_site.py 生成）--"]
    s1, n1 = build_industry_lines()
    parts += s1
    s2, n2 = build_tracking_rules()
    parts += ['']
    parts += s2

    con = sqlite3.connect('file:' + ANALYTICS_DB + '?mode=ro', uri=True)
    cur = con.cursor()
    con.executescript('BEGIN')
    per = fetch_per_stock(cur)
    print('stock-analytics 匹配:', len(per), '/ 145')
    s3, n3 = build_pe_history(per)
    parts += ['']
    parts += s3
    s4, n4 = build_tracking_data(per)
    parts += ['']
    parts += s4
    s5, n5 = build_finance_modules(cur)
    con.close()

    parts += ['']
    parts += s5
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write('\n'.join(parts))
    print(f'OK → {OUT}')
    print(f'  industry_lines: {n1} 行（含 lineCat）')
    print(f'  tracking_rules: {n2} 行（行业红绿灯）')
    print(f'  pe_history: {n3} 行 ({PE_DAYS} 天/只)')
    print(f'  tracking_data: {n4} 行（9 维）')
    print(f'  财务模块: {n5} 只')


if __name__ == '__main__':
    main()