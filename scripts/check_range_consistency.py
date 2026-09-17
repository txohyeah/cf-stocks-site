#!/usr/bin/env python3
"""站点 ttm_buy_range ↔ 估值模块档位表 一致性检查（只读）。

背景：站点每只票的「便宜线/贵线」应等于其估值模块档位表的「合理区」两端。
历史上有三类错：①口径标错（数值是 A 口径、单位记成 B）②区间过期 ③对齐的是旧口径行。

本脚本把模块档位表的合理区（无合理区则「低估线↔高估线」拼接）换算到站点口径后比对：
    一致           0.85 ≤ 两项比率 ≤ 1.18
    站点偏高(假便宜) 任一比率 > 1.18  → 会把贵区当便宜区，危险
    站点偏保守      比率 < 0.85       → 只会少报便宜，不危险
    无法换算        缺 BPS/PE/流通股等换算要素
    无档位表        模块里没有可解析的合理区

单位识别（模块档位表第二列）：
    含「元」→ price；含 PE/倍 → pe；含「亿」且含「市值」→ mv（须换算成价格再比）
换算桥：price = pe × (现价/PE_ttm)；price = 市值 / 总股本；pb = price / BPS，BPS = 现价/PB。

用法：
    /home/application/stock-analytics/venv/bin/python scripts/check_range_consistency.py
    ... --json out.json   # 另存结果
"""
import argparse
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cf_d1  # noqa: E402

STOCK_DB = '/home/application/stock-analytics/data/stock.db'
NUM = re.compile(r'(\d+(?:\.\d+)?)')


def one(sql):
    d = cf_d1.call('POST', '/accounts/%s/d1/database/%s/query' % (
        cf_d1.ACCOUNT_ID, cf_d1.find_db()['uuid']), {'sql': sql})
    if not d.get('success'):
        raise SystemExit('SQL 失败: ' + json.dumps(d.get('errors'), ensure_ascii=False))
    return d['result'][0]['results']


def unit_of(cell, key):
    if re.search(r'PE|倍', cell, re.I):
        return 'pe'
    if '元' in cell:
        return 'price'
    if '亿' in cell and ('市值' in cell or '市值' in key):
        return 'mv'
    return None


def parse_band(blocks):
    """blocks: [(key, [cell,...]), ...] → (unit, lo, hi, basis) 或 None"""
    cands = []
    for key, cells in blocks:
        for cell in cells[1:2]:  # 第二列才是数值列
            u = unit_of(cell, key)
            if not u:
                continue
            nums = [abs(float(x)) for x in NUM.findall(cell)]
            if len(nums) >= 2 and nums[1] > nums[0]:
                cands.append((key, u, nums[0], nums[1]))
            elif len(nums) == 1:
                cands.append((key, u, nums[0], None))
    for key, u, lo, hi in cands:
        if '合理区' in key and hi:
            return u, lo, hi, '合理区'
    lo = lo_u = hi = hi_u = None
    for key, u, a, b in cands:
        if '低估区' in key and a is not None:
            lo, lo_u = a, u
        if '高估区' in key and a is not None:
            hi, hi_u = a, u
    if lo and hi and hi > lo:
        return lo_u, lo, hi, '低估↔高估拼接'
    return None


def to_price(unit, lo, hi, price, pe, shares):
    if unit == 'price':
        return lo, hi
    if unit == 'mv':
        if not (shares and shares > 0):
            return None
        return lo * 1e8 / shares, hi * 1e8 / shares
    if unit == 'pe':
        if not (price and pe):
            return None
        return lo * price / pe, hi * price / pe
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='')
    a = ap.parse_args()

    stocks = one("SELECT code,name,category,ttm_buy_range,buy_range_type,pe_current FROM stocks "
                 "WHERE tracked=1 ORDER BY code")
    mods = one("""SELECT m.stock_code, b.data_json FROM stock_modules m JOIN module_blocks b
                  ON b.module_id = m.id WHERE m.module_key='valuation' AND b.block_type='table'""")
    stated = {}
    for r in one("""SELECT s.code, b.data_json FROM stocks s JOIN stock_modules m ON m.stock_code=s.code
                    JOIN module_blocks b ON b.module_id=m.id WHERE b.data_json LIKE '%uyRange%'"""):
        t = re.findall(r'[Tt]tmBuyRange[^0-9\[\]]*(\[[^\]]*\])', r['data_json'])
        if t:
            stated.setdefault(r['code'], t[0])

    band_by = {}
    for r in mods:
        try:
            rows = json.loads(r['data_json']).get('rows', [])
        except Exception:
            continue
        blk = [(str(x[0]), [str(c) for c in x]) for x in rows
               if isinstance(x, list) and re.search(r'合理区|低估区|高估区', str(x[0]))]
        if blk:
            band_by.setdefault(r['stock_code'], []).extend(blk)

    c = sqlite3.connect(STOCK_DB)
    last = c.execute('SELECT MAX(trade_date) FROM daily_basic').fetchone()[0]
    mkt = {r[0]: (r[1], r[2], r[3]) for r in c.execute(
        'SELECT ts_code,close,pb,total_mv FROM daily_basic WHERE trade_date=?', (last,))}

    res = []
    for s in stocks:
        code = s['code']
        price = pb = mv = None
        if code in mkt:
            price, pb, mv = mkt[code][0], mkt[code][1], mkt[code][2]
        try:
            lo, hi = [float(x) for x in json.loads(s['ttm_buy_range'])]
        except Exception:
            lo = hi = None
        st = s['buy_range_type']
        pe = s['pe_current']
        shares = (mv * 1e8 / price) if (mv and price) else None
        mb = parse_band(band_by.get(code, [])) if code in band_by else None
        rec = dict(code=code, name=s['name'], cat=s['category'], site=[lo, hi], site_type=st,
                   stated=stated.get(code), module=mb)
        if not mb:
            rec['verdict'] = '无档位表/无合理区'
            res.append(rec)
            continue
        unit, mlo, mhi, basis = mb
        p = to_price(unit, mlo, mhi, price, pe, shares)
        if not p:
            rec['verdict'] = '无法换算'
            res.append(rec)
            continue
        plo, phi = p
        if st == 'price':
            slo, shi = plo, phi
        elif st in ('pe', 'pe-fwd', 'pe-core'):
            if not (price and pe):
                rec['verdict'] = '无法换算(缺PE)'
                res.append(rec)
                continue
            slo, shi = plo * pe / price, phi * pe / price
        elif st == 'pb':
            if not (price and pb):
                rec['verdict'] = '无法换算(缺PB)'
                res.append(rec)
                continue
            bps = price / pb
            slo, shi = plo / bps, phi / bps
        else:  # ps 等
            rec['verdict'] = '无法换算(%s口径无源)' % st
            res.append(rec)
            continue
        rec['expect'] = [round(slo, 3), round(shi, 3)]
        if lo and hi:
            r1, r2 = lo / slo, hi / shi
            rec['ratio'] = [round(r1, 2), round(r2, 2)]
            # 危险方向只在「下沿抬高」：便宜线高于模块合理区下沿 → 现价还在合理/高估区，站点却报低估
            if r1 > 1.18:
                rec['verdict'] = '⚠️便宜线偏高(假便宜)'
            elif r1 < 0.85:
                rec['verdict'] = '🔵便宜线偏严(保守)'
            elif r2 > 1.18:
                rec['verdict'] = '🔵贵线偏松(漏报高估)'
            elif r2 < 0.85:
                rec['verdict'] = '🔵贵线偏严'
            else:
                rec['verdict'] = '✅一致'
        else:
            rec['verdict'] = '⚠️站点无有效区间'
        res.append(rec)

    print('行情日期 %s ｜ 有档位表 %d 只 ｜ 模块自述 ttmBuyRange %d 只' % (
        last, len(band_by), len(stated)))
    print('%-11s %-8s %-6s %-16s %-18s %-16s %s' % (
        'code', 'name', 'cat', '站点区间', '模块带(原单位)', '应为(站点口径)', '判定'))
    print('-' * 140)
    order = ['⚠️便宜线偏高(假便宜)', '⚠️站点无有效区间', '🔵便宜线偏严(保守)', '🔵贵线偏松(漏报高估)', '🔵贵线偏严', '✅一致', '无法换算', '无档位表/无合理区']
    for rec in sorted(res, key=lambda r: (order.index(r['verdict']), r['code'])):
        mb = rec['module']
        print('%-11s %-8s %-6s %-16s %-18s %-16s %s %s' % (
            rec['code'], rec['name'][:8], rec['cat'][:6],
            '%s~%s/%s' % (rec['site'][0], rec['site'][1], rec['site_type']),
            '%s %s~%s%s' % (mb[0], mb[1], mb[2], '' if mb[3] == '合理区' else '[拼]') if mb else '—',
            '%.2f~%.2f' % tuple(rec['expect']) if 'expect' in rec else '—',
            rec['verdict'], rec.get('ratio', '')))
    cnt = {}
    for rec in res:
        cnt[rec['verdict']] = cnt.get(rec['verdict'], 0) + 1
    print('\n汇总：' + '，'.join('%s %d' % (k, v) for k, v in cnt.items()))

    if a.json:
        json.dump(dict(asof=last, rows=res), open(a.json, 'w'), ensure_ascii=False, indent=1)
        print('已写 %s' % a.json)


if __name__ == '__main__':
    main()
