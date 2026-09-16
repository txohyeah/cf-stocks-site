#!/usr/bin/env python3
"""stocks 站点详情数据导出管线 v2
输入：
  - media/u4_site_archive/api_stocks.json       → industry_lines（含 lineCat）
  - media/u4_site_archive/api_industries.json   → tracking_rules（行业红绿灯规则）
  - stock-analytics/data/stock.db               → pe_history（近730交易日）/ tracking_data（头部9维）/ 财务模块（income+fina_indicator+cashflow）
输出：
  - projects/stocks-site/data/detail_seed.sql
用法：
  python3 scripts/export_site.py              # 默认：只导出「和 D1 现值不一致」的部分
  python3 scripts/export_site.py --full       # 全量导出（空库重建用；不改 DELETE，仍不删全表）
  python3 scripts/export_site.py --dry-run    # 只统计不落文件
  python3 scripts/cf_d1.py exec ../data/detail_seed.sql

======================================================================
🛑 2026-09-16 安全改造（别改回去）
原实现给 5 张表都生成 `DELETE FROM <表>;` + 全量 INSERT，最狠的是 pe_history
（10 万行）。后果有两个，都是致命的：
  1) **写额度**：D1 免费版每日行写上限 100,000（DELETE 也按删除行数计写）。
     "删 10 万 + 插 10 万" = 一次执行 20 万行写 = 日额度的 2 倍 → code 7500 整条失败。
  2) **内容事故**：`DELETE FROM module_blocks;` + `DELETE FROM stock_modules;` 是
     **全表清空** —— 跑一次会把站上所有模块内容（含站内手工维护的）全删掉，
     只有脚本会重建的 finance 模块能活下来。
现在：
  - 默认**两级比对**：先用指纹筛出"可能变了"的股票（一次 GROUP BY，省得全表逐行拉），
    再对这批股票逐行比对（fetch_d1_pe），只写 D1 缺的、值不同的行。
    pe_history 用 (行数, 最新交易日, PE 求和取 2 位小数) 做指纹（抓得住变化、不吃浮点噪声）。
  - DELETE 一律带 WHERE 且只针对该股票；pe_history 干脆不删，改 UPSERT
  - 护栏 1：生成结果里若出现无 WHERE 的 DELETE，直接报错退出（自检）
  - 护栏 2：预计写行数超过 MAX_WRITE_ROWS 时拒绝生成，除非显式 --allow-bulk
======================================================================
"""
import argparse
import json
import os
import re
import sqlite3
import sys

import paths

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import execute_sql, find_db   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # projects/stocks-site
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))                       # workspaces/default
ARCHIVE = os.path.join(WORKSPACE, 'media', 'u4_site_archive')
ANALYTICS_DB = paths.STOCK_ANALYTICS_DB
OUT = os.path.join(ROOT, 'data', 'detail_seed.sql')

PE_DAYS = 730             # PE 历史天数（stock-analytics 有 3 年数据）
INSERT_BATCH = 800        # 每条 INSERT 的 VALUES 行数（~80KB/条，D1 body 上限内）
MAX_WRITE_ROWS = 20000    # 单次生成的写行数上限（超过需 --allow-bulk）
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


# ---------------------------------------------------------------- D1 现状指纹
def d1_state(db):
    """读 D1 每只股票的现状指纹，用于"只写变化"。返回 {表名: {code: 指纹元组}}。

    只读，不动写额度（pe_history 那条约 10 万行**读**，占免费版 5,000,000 行/日的 ~2%）。
    """
    state = {}

    def grab(key, sql, drop=('stock_code',)):
        ok, rows, _m, err = execute_sql(db, sql)
        if not ok:
            raise SystemExit(f'{key} 指纹读取失败: {err}')
        state[key] = {r['stock_code']: tuple(v for k, v in r.items() if k not in drop) for r in rows}

    grab('pe_history',
         "SELECT stock_code, COUNT(*) n, MAX(trade_date) mx, ROUND(SUM(pe_ttm), 2) s "
         "FROM pe_history GROUP BY stock_code")
    grab('tracking_data',
         "SELECT stock_code, COUNT(*) n, MAX(as_of) mx FROM tracking_data GROUP BY stock_code")
    grab('industry_lines',
         "SELECT stock_code, COUNT(*) n FROM industry_lines GROUP BY stock_code")
    grab('tracking_rules',
         "SELECT stock_code, COUNT(*) n FROM tracking_rules GROUP BY stock_code")
    grab('finance',
         "SELECT sm.stock_code, COUNT(b.id) n, COALESCE(SUM(LENGTH(b.data_json)), 0) L "
         "FROM stock_modules sm LEFT JOIN module_blocks b ON b.module_id = sm.id "
         "WHERE sm.module_key = 'finance' GROUP BY sm.stock_code")
    return state


def pick(built, d1fp, full):
    """筛出「本地指纹 ≠ D1 指纹」的股票。built: {code: (指纹, [行字符串])}"""
    if full:
        return {c: v for c, v in built.items()}
    return {c: v for c, v in built.items() if d1fp.get(c) != v[0]}


# ---------------------------------------------------------------- 各表构建（返回 {code: (指纹, 行)}）
def build_industry_lines():
    out = {}
    for s in load_stocks():
        rows, code = [], s['code']
        for i, r in enumerate(s.get('industryRoles') or []):
            rows.append(
                f"('{q(code)}', '{q(r.get('id', ''))}', '{q(r.get('position', ''))}', "
                f"'{q(r.get('weight', ''))}', '{q(r.get('lineCat', ''))}', "
                f"'{q(r.get('segment', ''))}', '{q(r.get('note', ''))}', {i})")
        if rows:
            out[code] = ((len(rows),), rows)
    return out


def build_tracking_rules():
    """行业红绿灯规则：股票按其产业线合并 industries.trackIndicators"""
    ind_rules = {x['id']: (x.get('trackIndicators') or []) for x in load_industries()}
    out = {}
    for s in load_stocks():
        code = s['code']
        seen = set()
        order = 0
        rows = []
        for r in s.get('industryRoles') or []:
            for rule in ind_rules.get(r.get('id'), []):
                key = (rule.get('indicator') or '')
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append(
                    f"('{q(code)}', '{q(key)}', '{q(key)}', '{q(rule.get('red', ''))}', "
                    f"'{q(rule.get('yellow', ''))}', '{q(rule.get('green', ''))}', {order})")
            order += 1
        if rows:
            out[code] = ((len(rows),), rows)
    return out


def fetch_per_stock(cur):
    """返回 {code: {'pe': [...], 'latest': {...9维}}}"""
    out = {}
    for s in load_stocks():
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
    """返回 {code: (指纹, [(交易日, PE), ...])}。

    指纹 = (行数, 最新交易日, PE 求和取 2 位小数) —— 与 d1_state 的 SQL 口径一致。
    求和只取 2 位小数是为了吃掉浮点噪声（同一批浮点数在 D1 与本地求和的末位差异），
    但单只股票任一行 PE 变动 ≥0.01 会被抓住。

    指纹只是**便宜的预筛**（一次 GROUP BY 顶掉全表逐行拉取），真正写多少由
    fetch_d1_pe() 的逐行比对决定 —— 否则"某只股票只要有一天不同"就会整只 736 行重写，
    145 只 = 10 万行 = 一天写额度。
    """
    out = {}
    for code, info in per.items():
        pe = info['pe']
        if not pe:
            continue
        fp = (len(pe), max(d for d, _ in pe), round(sum(v for _, v in pe), 2))
        out[code] = (fp, list(pe))
    return out


def fetch_d1_pe(db, codes):
    """只对预筛出「可能变了」的股票，从 D1 拉现有 PE 行 → {code: {交易日: PE}}。只读。"""
    out = {}
    for i in range(0, len(codes), 20):
        batch = codes[i:i + 20]
        inlist = ','.join("'%s'" % q(c) for c in batch)
        ok, rows, _m, err = execute_sql(
            db, f"SELECT stock_code, trade_date, pe_ttm FROM pe_history WHERE stock_code IN ({inlist})")
        if not ok:
            raise SystemExit(f'pe_history 逐行比对读取失败: {err}')
        for r in rows:
            out.setdefault(r['stock_code'], {})[r['trade_date']] = r['pe_ttm']
    return out


def emit_pe_history(picked, d1pe, full):
    """逐行比对后 UPSERT：只写「D1 没有的」和「值不同的」行。

    D1 多出来的行（比如本地上游只留 730 天、D1 留着 736 天）**不删** —— 孤行无害，
    而 DELETE 是按删除行数计写额度的，能省就省。
    """
    stmts, n_rows, n_codes = [], 0, 0
    for code in sorted(picked):
        _fp, pairs = picked[code]
        have = {} if full else d1pe.get(code, {})
        todo = []
        for d, v in pairs:
            old = have.get(d)
            if old is None or abs(float(old) - float(v)) > 1e-6:
                todo.append(f"('{q(code)}', '{d}', {v})")
        if not todo:
            continue
        n_codes += 1
        n_rows += len(todo)
        stmts.append(f'-- {code}: {len(todo)} 行（本地 {len(pairs)} 行，D1 已有 {len(have)} 行）')
        for ch in chunks(todo):
            stmts.append("INSERT INTO pe_history (stock_code, trade_date, pe_ttm) VALUES\n" + ",\n".join(ch) +
                         " ON CONFLICT(stock_code, trade_date) DO UPDATE SET pe_ttm = excluded.pe_ttm;")
    if n_rows:
        stmts.insert(0, f'-- pe_history（逐行比对：{n_codes} 只 / {n_rows} 行需要写）')
    return stmts, n_rows, n_codes


def build_tracking_data(per):
    dims_order = ['close', 'pe_lyr', 'pe_ttm', 'pb', 'dv_ratio', 'total_mv', 'circ_mv', 'turnover_rate', 'volume_ratio']
    key_map = {'pe_lyr': 'pe', 'pe_ttm': 'pe_ttm', 'close': 'close', 'pb': 'pb', 'dv_ratio': 'dv_ratio',
               'total_mv': 'total_mv', 'circ_mv': 'circ_mv', 'turnover_rate': 'turnover_rate',
               'volume_ratio': 'volume_ratio'}
    out = {}
    for code, info in per.items():
        l = info['latest']
        if l is None:
            continue
        rows = []
        for dim in dims_order:
            val = l[key_map[dim]]
            if val is None:
                continue
            rows.append(f"('{q(code)}', '{dim}', '{val}', '{l['trade_date']}')")
        if rows:
            out[code] = ((len(rows), l['trade_date']), rows)
    return out


def build_finance_modules(cur):
    """关键财务数据模块：归母净利/EPS/ROE/营收/经营现金流 × 4 期

    指纹 = (块数=1, data_json 长度)，与 d1_state 的 finance 指纹口径一致。
    返回 {code: (指纹, stock_modules 行, module_blocks 行)}
    """
    out = {}
    placeholders = ','.join('?' * len(FIN_PERIODS))
    for s in load_stocks():
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
        sm = ("INSERT INTO stock_modules (stock_code, module_key, title, template_key, sort_order, visible) VALUES "
              f"('{q(code)}', 'finance', '关键财务数据', 'finance', 1, 1);")
        mb = ("INSERT INTO module_blocks (module_id, block_type, data_json, sort_order) VALUES "
              f"(last_insert_rowid(), 'table', '{q(data)}', 0);")
        out[code] = ((1, len(data)), sm, mb)
    return out


# ---------------------------------------------------------------- 生成
NO_WHERE_DELETE = re.compile(r'^\s*DELETE\s+FROM\s+\w+\s*;\s*$', re.I | re.M)


def chunks(rows):
    return [rows[i:i + INSERT_BATCH] for i in range(0, len(rows), INSERT_BATCH)]


def emit(table, cols, picked, header, per_code_delete=False, upsert=False):
    """把 {code: (指纹, 行)} 生成 SQL。返回 (语句列表, 写入行数估算)。"""
    if not picked:
        return [], 0
    stmts = [f'-- {header}（{len(picked)} 只）']
    n = 0
    for code in sorted(picked):
        rows = picked[code][1]
        if per_code_delete:
            stmts.append(f"DELETE FROM {table} WHERE stock_code = '{q(code)}';")
            n += len(rows)     # DELETE 也计写（按删除行数），按"最多删这么多"估
        for ch in chunks(rows):
            tail = ' ON CONFLICT(stock_code, trade_date) DO UPDATE SET pe_ttm = excluded.pe_ttm' if upsert else ''
            stmts.append(f"INSERT INTO {table} ({cols}) VALUES\n" + ",\n".join(ch) + ";" + tail)
        n += len(rows)
    return stmts, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true', help='全量导出（空库重建用），不做 D1 差异比对')
    ap.add_argument('--dry-run', action='store_true', help='只统计不写文件')
    ap.add_argument('--allow-bulk', action='store_true', help=f'允许超过 {MAX_WRITE_ROWS} 行的批量生成')
    args = ap.parse_args()

    db = find_db()
    if not db:
        raise SystemExit('D1 不存在')
    if args.full:
        print('模式：全量（--full）')
        state = {k: {} for k in ('pe_history', 'tracking_data', 'industry_lines', 'tracking_rules', 'finance')}
    else:
        print('模式：只写变化（默认，省 D1 写额度）')
        state = d1_state(db)

    parts = ['-- stocks 站点 P2 详情种子 v2（export_site.py 生成）--']
    stats, total = [], 0

    s = pick(build_industry_lines(), state['industry_lines'], args.full)
    st, n = emit('industry_lines', 'stock_code, line_id, position, weight, lineCat, segment, note, sort_order',
                 s, 'industry_lines（含 lineCat）', per_code_delete=True)
    parts += [''] + st
    stats.append(('industry_lines', len(s), len(s), n))
    total += n

    s = pick(build_tracking_rules(), state['tracking_rules'], args.full)
    st, n = emit('tracking_rules', 'stock_code, dimension, indicator, red, yellow, green, sort_order',
                 s, 'tracking_rules（行业红绿灯）', per_code_delete=True)
    parts += [''] + st
    stats.append(('tracking_rules', len(s), len(s), n))
    total += n

    con = sqlite3.connect('file:' + ANALYTICS_DB + '?mode=ro', uri=True)
    cur = con.cursor()
    con.executescript('BEGIN')
    per = fetch_per_stock(cur)
    print('stock-analytics 匹配:', len(per), '只')
    pe_built = build_pe_history(per)
    s = pick(pe_built, state['pe_history'], args.full)
    d1pe = {} if args.full else fetch_d1_pe(db, list(s))
    st, n, n_codes = emit_pe_history(s, d1pe, args.full)
    parts += [''] + st
    stats.append(('pe_history', n_codes, len(pe_built), n))
    total += n

    s = pick(build_tracking_data(per), state['tracking_data'], args.full)
    st, n = emit('tracking_data', 'stock_code, dimension, value, as_of', s, 'tracking_data（9 维）',
                 per_code_delete=True)
    parts += [''] + st
    stats.append(('tracking_data', len(s), len(build_tracking_data(per)), n))
    total += n

    fin = build_finance_modules(cur)
    con.close()
    s = pick(fin, state['finance'], args.full)
    if s:
        st = [f'-- 财务模块（stock_modules + module_blocks，{len(s)} 只；DELETE 按 code+module_key 收窄）']
        fn = 0
        for code in sorted(s):
            st.append("DELETE FROM module_blocks WHERE module_id IN "
                      f"(SELECT id FROM stock_modules WHERE stock_code = '{q(code)}' AND module_key = 'finance');")
            st.append("DELETE FROM stock_modules WHERE stock_code = "
                      f"'{q(code)}' AND module_key = 'finance';")
            st.append(s[code][1])
            st.append(s[code][2])
            fn += 2
        parts += [''] + st
        stats.append(('财务模块', len(s), len(fin), fn))
        total += fn

    sql_text = '\n'.join(parts)

    # 护栏 1：绝不允许无 WHERE 的 DELETE
    bad = NO_WHERE_DELETE.findall(sql_text)
    if bad:
        print(f'[FAIL] 生成结果里出现无 WHERE 的 DELETE（会清表）：{bad}')
        raise SystemExit(1)

    # 护栏 2：写行数上限
    print()
    print(f'{"表":<16}{"本次写":>8}{"总量":>8}{"估算写行数":>12}')
    for name, n_changed, n_all, n_rows in stats:
        print(f'{name:<16}{n_changed:>8}{n_all:>8}{n_rows:>12,}')
    print(f'{"合计":<16}{"":>8}{"":>8}{total:>12,}')
    if total > MAX_WRITE_ROWS and not args.allow_bulk:
        print(f'\n[FAIL] 估算写 {total:,} 行，超过上限 {MAX_WRITE_ROWS:,}（D1 免费版日额度 100,000 行写）。')
        print('       确认无误请加 --allow-bulk；只补变化请去掉 --full。')
        raise SystemExit(1)

    if args.dry_run:
        print('\n[DRY-RUN] 未写文件')
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write(sql_text)
    print(f'\nOK → {OUT}（{len(sql_text.splitlines())} 行 SQL，估算写 {total:,} 行）')
    if total:
        print(f'     执行：python3 scripts/cf_d1.py exec data/detail_seed.sql')


if __name__ == '__main__':
    main()
