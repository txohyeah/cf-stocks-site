#!/usr/bin/env python3
"""复现 worker /api/stocks-detail 的取数逻辑，验证站点详情页渲染源（不涉登录）。

用法：
    python3 scripts/verify_detail.py 002487.SZ
    python3 scripts/verify_detail.py 002487.SZ,002531.SZ

    # 需要锁死具体值（如核对某次更新是否真的生效）时追加可选断言：
    python3 scripts/verify_detail.py 301611.SZ --expect-category frontier \\
        --expect-range "[26, 60]" --expect-modules 5

默认只跑与个股无关的通用断言（记录存在 / 分类合法 / 买点区间可解析 /
模块 block 非空且 JSON 可解析 / pe_history 非空）；任一断言失败退出码为 1，
可用 $? 在脚本化流程里判断。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_d1

VALID_CATEGORIES = ('core', 'frontier', 'swing', 'dividend', 'sunset')
db = cf_d1.find_db()


def run(sql, *params):
    s = sql
    for p in params:
        s = s.replace('?', "'" + str(p) + "'", 1)
    ok, rows, _meta, err = cf_d1.execute_sql(db, s)
    if not ok:
        raise SystemExit('SQL 失败: ' + json.dumps(err, ensure_ascii=False)[:300])
    return rows


def check_one(code, args):
    """校验单只标的，返回 (fails, warns)"""
    fails, warns = [], []
    print(f'\n========== {code} ==========')

    stock = run('SELECT code, name, sector, category, subtype, tags, desc, pe_current, pe_date, '
                'ttm_buy_range, buy_range_type FROM stocks WHERE code = ?', code)
    print('== stock ==')
    if not stock:
        print('  ❌ stocks 表无该记录')
        return ['stocks 表无该记录'], warns
    s = stock[0]
    for k, v in s.items():
        print(f'  {k}: {str(v)[:110]}')

    # ——— 通用断言：字段规格 ———
    if not s['category']:
        fails.append('category 为空')
    elif s['category'] not in VALID_CATEGORIES:
        fails.append(f"category 非法: {s['category']}")

    br = (s['ttm_buy_range'] or '').strip()
    if br:
        try:
            if not isinstance(json.loads(br), list):
                fails.append('ttm_buy_range 不是数组')
        except Exception:
            fails.append(f'ttm_buy_range 不是合法 JSON: {br[:60]}')
    else:
        warns.append('ttm_buy_range 为空（未设买点区间）')

    lines = run('SELECT line_id, position, weight, lineCat, segment, substr(note,1,70) note '
                'FROM industry_lines WHERE stock_code = ? ORDER BY sort_order, id', code)
    print('== lines ==', len(lines))
    for l in lines:
        print(' ', l)
    if not lines:
        warns.append('未挂产业线（industry_lines 为空）')
    elif args.category_required and not any(l['lineCat'] for l in lines):
        warns.append("产线 lineCat 未标 → 重收时加 --line-cat（core 主脉常标 mainline）")

    mods = run('SELECT id, module_key, title, template_key, sort_order FROM stock_modules '
               'WHERE stock_code = ? AND visible = 1 ORDER BY sort_order, id', code)
    ids = [m['id'] for m in mods]
    blocks = run(f'SELECT module_id, block_type, data_json, sort_order FROM module_blocks WHERE module_id IN '
                 f'({",".join(str(i) for i in ids)}) ORDER BY module_id, sort_order, id') if ids else []
    by = {}
    for b in blocks:
        by.setdefault(b['module_id'], []).append(b)

    print('== modules ==', len(mods))
    for m in mods:
        bs = by.get(m['id'], [])
        bad = 0
        for b in bs:
            try:
                json.loads(b['data_json'] or '{}')
            except Exception:
                bad += 1
        if bad:
            fails.append(f"模块 {m['module_key']} 有 {bad} 个 block JSON 损坏")
        if not bs:
            fails.append(f"模块 {m['module_key']} 无 block")
        types = ', '.join(b['block_type'] for b in bs)
        print(f"  [{m['sort_order']}] {m['module_key']:20s} {m['title']:14s} blocks={len(bs)} JSON坏={bad}  types: {types}")
    if not mods:
        warns.append('无重点内容模块（stock_modules 为空）')

    rules = run('SELECT dimension, indicator, red, yellow, green FROM tracking_rules '
                'WHERE stock_code = ? ORDER BY sort_order, id', code)
    cats = run('SELECT name, due_date, status FROM catalysts WHERE stock_code = ? ORDER BY sort_order, id', code)
    risk = run('SELECT rating, rating_zone, reasons FROM risk_checks WHERE stock_code = ?', code)
    pe = run('SELECT COUNT(*) n, MIN(trade_date) a, MAX(trade_date) b FROM pe_history WHERE stock_code = ?', code)

    print('== tracking_rules ==', len(rules))
    for r in rules:
        print('  ', r['dimension'], '|', r['indicator'][:40])
    if not rules:
        warns.append('无跟踪规则（tracking_rules 为空）')

    print('== catalysts ==', len(cats))
    for c in cats:
        print('  ', c['due_date'], c['name'], c['status'])

    print('== risk_checks ==', risk[0]['rating'] if risk else None,
          '| 触发项', len(json.loads(risk[0]['reasons'])) if risk else '-')
    if not risk:
        warns.append('无暴雷检查记录 → 运行 python3 scripts/sync_baolei.py --codes ' + code + ' --exec')

    print('== pe_history ==', pe[0])
    if not pe[0]['n']:
        fails.append('pe_history 为空 → 运行 python3 scripts/backfill_pe.py --code ' + code)

    # ——— 可选断言：只在显式传入时生效（避免把某只票的值写死在脚本里）———
    if args.expect_category and s['category'] != args.expect_category:
        fails.append(f"category 期望 {args.expect_category}，实际 {s['category']}")
    if args.expect_range is not None and (s['ttm_buy_range'] or '') != args.expect_range:
        fails.append(f"买点区间期望 {args.expect_range}，实际 {s['ttm_buy_range']}")
    if args.expect_modules is not None and len(mods) != args.expect_modules:
        fails.append(f"模块数期望 {args.expect_modules}，实际 {len(mods)}")

    return fails, warns


def main():
    ap = argparse.ArgumentParser(description='校验站点详情页渲染源')
    ap.add_argument('codes', help='ts_code，多个用逗号分隔（如 002487.SZ,002531.SZ）')
    ap.add_argument('--expect-category', help='可选：断言 category（如 frontier）')
    ap.add_argument('--expect-range', help='可选：断言 ttm_buy_range 原样值（如 "[26, 60]"）')
    ap.add_argument('--expect-modules', type=int, help='可选：断言重点内容模块数量')
    ap.add_argument('--category-required', action='store_true', default=True,
                    help='要求产业线标注 lineCat（默认开）')
    ap.add_argument('--no-category-required', dest='category_required', action='store_false',
                    help='关闭 lineCat 标注要求')
    args = ap.parse_args()

    codes = [c.strip() for c in args.codes.split(',') if c.strip()]
    if not codes:
        raise SystemExit('请提供至少一个 ts_code')

    all_fails, all_warns = {}, {}
    for code in codes:
        f, w = check_one(code, args)
        all_fails[code] = f
        all_warns[code] = w

    print('\n' + '=' * 48)
    n_fail = sum(len(v) for v in all_fails.values())
    n_warn = sum(len(v) for v in all_warns.values())
    for code in codes:
        for msg in all_fails[code]:
            print(f'  ❌ [{code}] {msg}')
        for msg in all_warns[code]:
            print(f'  ⚠️  [{code}] {msg}')
    if n_fail:
        print(f'\n[FAIL] {len(codes)} 只标的，{n_fail} 项失败 / {n_warn} 项提醒')
        return 1
    print(f'\n[PASS] {len(codes)} 只标的详情页渲染源校验通过（{n_warn} 项提醒）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
