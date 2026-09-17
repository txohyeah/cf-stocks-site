#!/usr/bin/env python3
"""财报季区间复核：站点 `stocks.ttm_buy_range` 的地基是否还成立。

背景（2026-09-16）：长电科技 600584 的区间 `[48,68]` 建在「2026E 净利 33-38 亿」上，
而公司 2026H1 实际仅 8.45 亿、8 家券商一致预期 19.9-23.0 亿；该区间自 8/18 收录后
从未随报表重算，PE 刷了两轮它没动。本脚本把这类问题变成"定期自己冒出来"。

三类检查：
  A 地基矛盾 —— 估值模块写的年度预测 vs 已披露实际，用「同股历史季节性」校准
  B 数据异常 —— [0,0] 占位 / JSON 坏 / 上下沿颠倒 / 类型与量级不符
  C 位置偏离 —— 现价 vs 区间（超上沿 / 跌破下沿），提示复核，非错误

用法：
  python3 check_range_vs_report.py           # 人类可读报告
  python3 check_range_vs_report.py --json    # 机器可读
  python3 check_range_vs_report.py --quiet   # 只在有问题时输出
退出码：0 无 A/B 类问题；1 存在 A 或 B 类问题；2 取数失败。
"""
import argparse
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cf_d1 import find_db, execute_sql  # noqa: E402

STOCK_DB = '/home/application/stock-analytics/data/stock.db'
# 值本身无单位，口径由 buy_range_type 决定
BASE_COL = {'price': 'close', 'pe': 'pe_ttm', 'pe-fwd': 'pe_ttm', 'pe-core': 'pe_ttm',
            'pb': 'pb', 'ps': 'ps_ttm'}
PERIODS = ['0630', '0930', '1231']
# 估值模块里「20XXE …净利/归母… N 亿」——数字前必须出现利润词，避免抓到"营收"
PAT = re.compile(r'20(2[6-9])\s*E[^。；\n]{0,40}?(?:净利|归母|净利润|利润|盈利)[^。；\n\d]{0,12}?'
                 r'(\d+(?:\.\d+)?)\s*(?:[-~至]\s*(\d+(?:\.\d+)?)\s*)?亿')


def load_site():
    db = find_db()
    ok, rows, _m, err = execute_sql(
        db, "SELECT code,name,category,pe_current,pe_date,ttm_buy_range,buy_range_type,desc "
            "FROM stocks WHERE tracked=1 ORDER BY code")
    if not ok:
        raise RuntimeError('读 stocks 失败: %s' % err)
    ok2, blocks, _m2, err2 = execute_sql(
        db, "SELECT m.stock_code, b.data_json FROM module_blocks b "
            "JOIN stock_modules m ON b.module_id=m.id WHERE m.module_key='valuation'")
    if not ok2:
        raise RuntimeError('读 module_blocks 失败: %s' % err2)
    return rows, blocks


def latest_trade_date(cur):
    return cur.execute('SELECT MAX(trade_date) FROM daily_basic').fetchone()[0]


def fin_all(cur, codes):
    """每只票的全部 report_type=1 期末值（亿元），以及最新披露的报告期。"""
    out = {}
    for code in codes:
        d = {}
        for end, ni, ann in cur.execute(
                "SELECT end_date, n_income_attr_p, ann_date FROM income "
                "WHERE ts_code=? AND report_type='1'", (code,)):
            if ni is None or end in d:
                continue
            d[end] = (ni / 1e8, ann)
        out[code] = d
    return out


def seasonal_ratio(fin, period):
    """同股历史「全年 / 该报告期累计」倍数（取近 3 个完整年度），period 形如 0630/0930。"""
    ys = sorted({e[:4] for e in fin if e.endswith('1231') and e[:4] >= '2022'})[-3:]
    ratios = []
    for y in ys:
        rp, fy = fin.get(y + period), fin.get(y + '1231')
        if not rp or not fy:
            continue
        h, f = rp[0], fy[0]
        if h > 0 and f > 0:
            ratios.append(f / h)
    return (min(ratios), max(ratios)) if ratios else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    try:
        stocks, blocks = load_site()
    except Exception as e:
        print('取数失败：%s' % e, file=sys.stderr)
        return 2

    cur = sqlite3.connect(STOCK_DB).cursor()
    D = latest_trade_date(cur)
    mkt = {ts: dict(close=cl, pe_ttm=pe, pb=pb, ps_ttm=ps) for ts, cl, pe, pb, ps in cur.execute(
        'SELECT ts_code, close, pe_ttm, pb, ps_ttm FROM daily_basic WHERE trade_date=?', (D,))}
    # 历史极值：**必须带 ts_code 过滤**——daily_basic 是全市场表，不加过滤要为 4 个口径
    # 各扫一遍全表，实测 2 分钟以上（cron 直接超时）。一次 CASE 聚合即可。
    codes = tuple(s['code'] for s in stocks)
    ph = ','.join('?' * len(codes))
    hist = {}
    for row in cur.execute(
            "SELECT ts_code, "
            "MIN(CASE WHEN close>0 THEN close END), MAX(CASE WHEN close>0 THEN close END), "
            "MIN(CASE WHEN pe_ttm>0 THEN pe_ttm END), MAX(CASE WHEN pe_ttm>0 THEN pe_ttm END), "
            "MIN(CASE WHEN pb>0 THEN pb END), MAX(CASE WHEN pb>0 THEN pb END), "
            "MIN(CASE WHEN ps_ttm>0 THEN ps_ttm END), MAX(CASE WHEN ps_ttm>0 THEN ps_ttm END) "
            "FROM daily_basic WHERE trade_date>=? AND ts_code IN (%s) GROUP BY ts_code" % ph,
            ('20230901',) + codes):
        ts, cmn, cmx, pmn, pmx, bmn, bmx, smn, smx = row
        hist[ts] = {'close': (cmn, cmx) if cmn else None, 'pe_ttm': (pmn, pmx) if pmn else None,
                    'pb': (bmn, bmx) if bmn else None, 'ps_ttm': (smn, smx) if smn else None}
    # 财务：同样限定池内标的（income 也是全市场表）
    fin = {}
    for ts, end, ni in cur.execute(
            "SELECT ts_code, end_date, n_income_attr_p FROM income WHERE report_type='1' "
            "AND ts_code IN (%s)" % ph, codes):
        if ni is None:
            continue
        fin.setdefault(ts, {}).setdefault(end, (ni / 1e8, None))

    val_text = {}
    # 已作废的旧地基记录（如长电「旧地基作废：原按 2026E 33-38 亿」）会被下面的正则
    # 当成当前预测，造成永久误报 —— 含这些标记的块一律跳过
    # 措辞越写越花：除了"作废/原按"，还有「站点原「…」假设失真」「已按中报实数重做」这类。
    # 命中任一即视为历史说明，不参与当前预测比对（否则华曙/长电会永久挂在 A 类）。
    DEAD = ('作废', '原按', '旧地基', '已废弃', '此前按', '曾按',
            '假设失真', '站点原', '已按中报', '原口径', '不再适用')
    for b in blocks:
        t = b['data_json'] or ''
        if any(k in t for k in DEAD):
            continue
        val_text.setdefault(b['stock_code'], []).append(t)

    A, A2, B, C, noquote = [], [], [], [], []
    # 券商一致预期缓存（由 prep_range_data.py 维护，见 data/cache/rc_pool.json）
    rc_cache = {}
    _p = os.path.join(HERE, '..', 'data', 'cache', 'rc_pool.json')
    if os.path.exists(_p):
        try:
            rc_cache = json.load(open(_p))
        except Exception:
            pass
    for s in stocks:
        code, name, typ = s['code'], s['name'], (s['buy_range_type'] or 'pe')
        rg = (s['ttm_buy_range'] or '').strip()
        m = mkt.get(code)
        parsed = None
        if rg and rg != '[]':
            try:
                a = json.loads(rg)
                if isinstance(a, list) and len(a) == 2:
                    parsed = (float(a[0]), float(a[1]))
            except Exception:
                B.append(dict(code=code, name=name, kind='区间 JSON 不可解析', detail=rg))
                continue
            if parsed and parsed == (0.0, 0.0):
                B.append(dict(code=code, name=name, kind='[0,0] 空占位（前端会显示 0~0x）', detail=rg))
                continue
            if parsed and parsed[0] > parsed[1]:
                B.append(dict(code=code, name=name, kind='上下沿颠倒', detail=rg))
                continue

        # A：地基 vs 最新报表
        lst = [x for x in (PAT.finditer(t) for t in val_text.get(code, [])) for x in x]
        hits = []
        for mm in lst:
            yr = int('20' + mm.group(1))
            a = float(mm.group(2))
            b = float(mm.group(3)) if mm.group(3) else a
            hits.append((yr, a, b, mm.group(0)[:52]))
        if hits and code in fin and fin[code]:
            # 最新已披露报告期（非 12/31）
            ends = sorted(e for e in fin[code] if e.endswith(tuple(PERIODS)) and not e.endswith('1231'))
            if ends:
                le = ends[-1]
                y, per = le[:4], le[4:]
                act = fin[code][le][0]
                cand = [h for h in hits if h[0] == int(y)]
                sr = seasonal_ratio(fin[code], per)
                if act and act > 0 and cand and sr:
                    hi = max(c[2] for c in cand)
                    need = hi / act
                    rel = need / sr[1]
                    if rel > 1.15:
                        # 用券商一致预期校准：模块预测 ≈ 券商预期 → 只是下半年集中确认收入，
                        # 不是地基塌了（2026-09-16 实测：A 类 11 只里 7 只是这类误报）
                        rcy = rc_cache.get(code, {}).get(y)
                        med = None
                        if rcy:
                            sv = sorted(rcy)
                            med = sv[len(sv) // 2]
                        dev = (hi - med) / med if med else None
                        item = dict(code=code, name=name, period=le, actual=round(act, 2),
                                    forecast_hi=hi, need=round(need, 2),
                                    hist='%.2f~%.2f' % sr, over=round((rel - 1) * 100),
                                    rc_med=med, dev=(round(dev * 100, 1) if dev is not None else None),
                                    evidence=cand[0][3])
                        # 无券商对照时保守保留在 A 类，避免漏掉真问题
                        (A2 if (dev is not None and dev <= 0.25) else A).append(item)

        if not m or not parsed:
            if not m:
                noquote.append(dict(code=code, name=name))
            continue
        col = BASE_COL.get(typ)
        if not col:
            B.append(dict(code=code, name=name, kind='未知 buy_range_type', detail=typ))
            continue
        cur_v = m[col]
        # B：类型与量级不符
        hr = hist.get(code, {}).get(col)
        if cur_v and hr and not (parsed[0] >= hr[0] * 0.7 and parsed[1] <= hr[1] * 1.3):
            B.append(dict(code=code, name=name, kind='区间与近三年实际取值脱节',
                          detail='%s 区间%s vs 现%s~%s' % (typ, rg, round(hr[0], 2), round(hr[1], 2))))
        # C：位置偏离
        if cur_v:
            d_lo = parsed[0] / cur_v - 1
            d_hi = parsed[1] / cur_v - 1
            if d_lo > 0.30:
                C.append(dict(code=code, name=name, typ=typ, rg=rg, cur=round(cur_v, 2),
                              pos='现价低于下沿', gap=round(-d_hi * 100, 1)))
            elif d_hi < -0.30:
                C.append(dict(code=code, name=name, typ=typ, rg=rg, cur=round(cur_v, 2),
                              pos='现价高于上沿', gap=round(-d_hi * 100, 1)))

    A.sort(key=lambda x: -(x['dev'] if x['dev'] is not None else x['over']))
    A2.sort(key=lambda x: -x['over'])
    if args.json:
        print(json.dumps(dict(as_of=D, trade_date=D, A=A, A2=A2, B=B, C=C,
                              no_quote=noquote, n_stocks=len(stocks)), ensure_ascii=False, indent=2))
    elif A or B or not args.quiet:
        print('区间复核报告（行情日 %s，池内 %d 只）' % (D, len(stocks)))
        print()
        print('=== A 类：估值地基与最新报表矛盾【真问题，需重算区间】%d 只 ===' % len(A))
        for x in A:
            dev = ('券商 %sE %.2f 亿，模块高 %+.0f%%' % (x['period'][:4], x['rc_med'], x['dev'])
                   if x['rc_med'] else '无券商对照')
            print(' 🔴 %-9s %-6s %s 实际 %.2f 亿 | 模块预测上限 %.1f 亿 → 需全年/该期 %.2f 倍'
                  '（历史 %s）| %s' % (x['code'], x['name'], x['period'], x['actual'],
                                     x['forecast_hi'], x['need'], x['hist'], dev))
        print()
        print('=== A2 类：季节性观察【疑似误报，模块预测与券商一致，通常无需改】%d 只 ===' % len(A2))
        for x in A2:
            print(' ⚪ %-9s %-6s 实际 %.2f 亿 | 模块 %.1f 亿 ≈ 券商 %sE %.2f 亿'
                  '（下半年集中确认收入所致，非地基问题）'
                  % (x['code'], x['name'], x['actual'], x['forecast_hi'],
                     x['period'][:4], x['rc_med']))
        print()
        print('=== B 类：区间数据异常 %d 只 ===' % len(B))
        for x in B:
            print(' %-9s %-6s %s | %s' % (x['code'], x['name'], x['kind'], x.get('detail', '')))
        print()
        print('=== C 类：现价偏离区间 >30%%（提示复核，非错误）%d 只 ===' % len(C))
        for x in C:
            print(' %-9s %-6s %-7s 区间%-13s 现价%-8s %s（距最近边界 %.1f%%）'
                  % (x['code'], x['name'], x['typ'], x['rg'], x['cur'], x['pos'], x['gap']))
        if noquote:
            print()
            print('=== 无行情数据 %d 只 ===' % len(noquote))
            print(' ' + ', '.join('%s %s' % (x['code'], x['name']) for x in noquote))
    return 1 if (A or B) else 0


if __name__ == '__main__':
    sys.exit(main())
