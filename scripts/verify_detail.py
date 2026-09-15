#!/usr/bin/env python3
"""复现 worker /api/stocks-detail 的取数逻辑，验证站点详情页渲染源（不涉登录）。

用法：python3 scripts/verify_detail.py 301611.SZ
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_d1

CODE = sys.argv[1] if len(sys.argv) > 1 else '301611.SZ'
db = cf_d1.find_db()


def run(sql, *params):
    s = sql
    for p in params:
        s = s.replace('?', "'" + str(p) + "'", 1)
    ok, rows, _meta, err = cf_d1.execute_sql(db, s)
    if not ok:
        raise SystemExit('SQL 失败: ' + json.dumps(err, ensure_ascii=False)[:300])
    return rows


stock = run('SELECT code, name, sector, category, subtype, tags, desc, pe_current, pe_date, ttm_buy_range, buy_range_type '
            'FROM stocks WHERE code = ?', CODE)
print('== stock ==')
for k, v in stock[0].items():
    print(f'  {k}: {str(v)[:110]}')

lines = run('SELECT line_id, position, weight, lineCat, segment, substr(note,1,70) note FROM industry_lines WHERE stock_code = ? '
            'ORDER BY sort_order, id', CODE)
print('== lines ==')
for l in lines:
    print(' ', l)

mods = run('SELECT id, module_key, title, template_key, sort_order FROM stock_modules WHERE stock_code = ? AND visible = 1 '
           'ORDER BY sort_order, id', CODE)
ids = [m['id'] for m in mods]
blocks = run(f'SELECT module_id, block_type, data_json, sort_order FROM module_blocks WHERE module_id IN '
             f'({",".join(str(i) for i in ids)}) ORDER BY module_id, sort_order, id') if ids else []
by = {}
for b in blocks:
    by.setdefault(b['module_id'], []).append(b)

print('== modules ==')
for m in mods:
    bs = by.get(m['id'], [])
    bad = 0
    for b in bs:
        try:
            json.loads(b['data_json'] or '{}')
        except Exception:
            bad += 1
    types = ', '.join(b['block_type'] for b in bs)
    print(f"  [{m['sort_order']}] {m['module_key']:20s} {m['title']:14s} blocks={len(bs)} JSON坏={bad}  types: {types}")

rules = run('SELECT dimension, indicator, red, yellow, green FROM tracking_rules WHERE stock_code = ? ORDER BY sort_order, id', CODE)
cats = run('SELECT name, due_date, status FROM catalysts WHERE stock_code = ? ORDER BY sort_order, id', CODE)
risk = run('SELECT rating, rating_zone, reasons FROM risk_checks WHERE stock_code = ?', CODE)
pe = run('SELECT COUNT(*) n, MIN(trade_date) a, MAX(trade_date) b FROM pe_history WHERE stock_code = ?', CODE)

print('== tracking_rules ==', len(rules))
for r in rules:
    print('  ', r['dimension'], '|', r['indicator'][:40])
print('== catalysts ==', len(cats))
for c in cats:
    print('  ', c['due_date'], c['name'], c['status'])
print('== risk_checks ==', risk[0]['rating'] if risk else None, '| 触发项', len(json.loads(risk[0]['reasons'])) if risk else '-')
print('== pe_history ==', pe[0])

# 关键字段断言
assert stock[0]['category'] == 'frontier', 'category 未更新'
assert stock[0]['ttm_buy_range'] == '[26, 60]', '买点未更新'
assert len(mods) == 5, f'模块数应为 5，实际 {len(mods)}'
assert all(len(by.get(m["id"], [])) > 0 for m in mods), '存在空模块'
print('\n[PASS] 详情页渲染源校验通过')
