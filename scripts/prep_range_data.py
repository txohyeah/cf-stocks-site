#!/usr/bin/env python3
"""为「区间重算」准备数据包。

背景：站点 166 只里有 17 只的 ttm_buy_range 需要重算（A 类地基矛盾 10 只 + B 类 [0,0] 占位 7 只，
长电科技 600584 已于 2026-09-16 完成）。判断「合理估值带」需要四类数据，本脚本一次拉齐：

  1) 行情估值 —— 现价/总市值/PE/PB/PS + 各自近三年分位（本地 stock.db）
  2) 财报     —— 近三年年报 + 最新报告期实际（本地 stock.db）
  3) 券商一致预期 —— tushare report_rc（卖方研报预测），按年度聚合出中位数与家数
  4) 站点模块 —— 估值模块里写的年度利润预测原文（站点 D1）

用法：
  cd projects/stocks-site
  /home/application/stock-analytics/venv/bin/python scripts/prep_range_data.py --codes 301018.SZ,688433.SH
  ... --codes all      # 用内置的 17 只待修清单
  ... --json out.json  # 另存 JSON
"""
import argparse
import json
import os
import re
import sqlite3
import time
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cf_d1 import find_db, execute_sql  # noqa: E402

STOCK_DB = '/home/application/stock-analytics/data/stock.db'
ENV = '/home/application/stock-analytics/.env'

# 17 只待修清单（长电 600584 已完成，不在此列）
PENDING = ['000063.SZ', '000811.SZ', '000688.SZ', '001203.SZ', '002126.SZ', '002536.SZ',
           '002821.SZ', '002837.SZ', '300420.SZ', '301018.SZ', '301123.SZ', '603203.SH',
           '688328.SH', '688383.SH', '688409.SH', '688433.SH', '688605.SH']
PAT = re.compile(r'20(2[6-9])\s*E[^。；\n]{0,40}?(?:净利|归母|净利润|利润|盈利)[^。；\n\d]{0,12}?'
                 r'(\d+(?:\.\d+)?)\s*(?:[-~至]\s*(\d+(?:\.\d+)?)\s*)?亿')


def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def read_token():
    for line in open(ENV):
        if line.startswith('TUSHARE_TOKEN'):
            return line.split('=', 1)[1].strip().strip('"\'')
    return ''


def rc_merge(df, cache):
    """把 report_rc 结果并入 cache：{ts_code: {year: [净利亿元, ...]}}

    坑：report_rc 的 `np` 单位是**万元**（长电 2028Q4 np=331345 → 33.1 亿），
    按 1e8 换算会得到 0.003 亿量级的错值。
    """
    for _, r in df.iterrows():
        np_ = r.get('np')
        qt = str(r.get('quarter') or '')
        if np_ is None or np_ != np_ or len(qt) < 6:   # NaN 判定
            continue
        try:
            yi = round(float(np_) / 1e4, 2)
        except Exception:
            continue
        if yi <= 0 or yi > 5000:
            continue
        cache.setdefault(str(r['ts_code']), {}).setdefault(qt[:4], []).append(yi)


def rc_for(codes, cache_path, max_age_days=7):
    """券商一致预期：优先用缓存（7 天内），否则拉区间全市场 + 单票补漏。

    限频：report_rc 每分钟 1 次，所以区间拉取要 sleep 63s；
    单次返回上限 5000 行（会截断），故按季度分段。
    """
    cache, fresh = {}, False
    if os.path.exists(cache_path):
        try:
            if (time.time() - os.path.getmtime(cache_path)) / 86400 < max_age_days:
                cache, fresh = json.load(open(cache_path)), True
        except Exception:
            pass
    pro = None
    need_interval = not fresh
    if need_interval:
        import tushare as ts
        pro = ts.pro_api(read_token())
        for s, e in [('20260101', '20260331'), ('20260401', '20260630'), ('20260701', '20260916')]:
            try:
                rc_merge(pro.report_rc(start_date=s, end_date=e), cache)
            except Exception as ex:
                print('区间 %s~%s 拉取失败: %s' % (s, e, str(ex)[:90]), file=sys.stderr)
            time.sleep(63)
    missing = [c for c in codes if not cache.get(c)]
    if missing:
        if pro is None:
            import tushare as ts
            pro = ts.pro_api(read_token())
        for c in missing:
            try:
                rc_merge(pro.report_rc(ts_code=c, start_date='20250101'), cache)
            except Exception as ex:
                print('%s 单票拉取失败: %s' % (c, str(ex)[:90]), file=sys.stderr)
            time.sleep(63)
    if need_interval or missing:
        d = os.path.dirname(cache_path)
        if d:
            os.makedirs(d, exist_ok=True)
        json.dump(cache, open(cache_path, 'w'))
    out = {}
    for c in codes:
        agg = cache.get(c) or {}
        out[c] = {y: dict(n=len(v), med=round(sorted(v)[len(v) // 2], 2),
                          lo=min(v), hi=max(v)) for y, v in sorted(agg.items())}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes', default='all')
    ap.add_argument('--json', default='')
    ap.add_argument('--rc-cache', default=os.path.join(HERE, '..', 'data', 'cache', 'rc_pool.json'))
    args = ap.parse_args()
    codes = PENDING if args.codes == 'all' else [c.strip() for c in args.codes.split(',') if c.strip()]

    cur = sqlite3.connect(STOCK_DB).cursor()
    D = cur.execute('SELECT MAX(trade_date) FROM daily_basic').fetchone()[0]

    out = {}
    for code in codes:
        name = (cur.execute('SELECT name FROM stock_basic WHERE ts_code=?', (code,)).fetchone() or [''])[0]
        m = cur.execute('SELECT close,total_mv,pe_ttm,pb,ps_ttm,dv_ratio FROM daily_basic '
                        'WHERE ts_code=? AND trade_date=?', (code, D)).fetchone()
        if not m:
            out[code] = dict(name=name, error='无当日行情')
            continue
        close, mv, pe, pb, ps, dv = m
        # 近三年估值分位
        q = {}
        for col in ['pe_ttm', 'pb', 'ps_ttm']:
            vals = [r[0] for r in cur.execute(
                "SELECT %s FROM daily_basic WHERE ts_code=? AND trade_date>=? AND %s>0 "
                "ORDER BY %s" % (col, col, col), (code, '20230901'))]
            vals = sorted(v for v in vals if v)
            q[col] = dict(p20=pct(vals, .2), p50=pct(vals, .5), p80=pct(vals, .8),
                          lo=vals[0] if vals else None, hi=vals[-1] if vals else None)
        # 财报：年报 + 最新报告期
        fin = {}
        for end, ni, rev in cur.execute(
                'SELECT end_date, n_income_attr_p, revenue FROM income WHERE report_type=\'1\' '
                'AND ts_code=?', (code,)):
            if end not in fin and ni is not None:
                fin[end] = dict(ni=round(ni / 1e8, 2), rev=round((rev or 0) / 1e8, 2))
        years = sorted(e for e in fin if e.endswith('1231'))
        latest_q = sorted((e for e in fin if e.endswith(('0331', '0630', '0930'))))[-3:]
        out[code] = dict(name=name, close=close, total_mv_yi=round(mv / 1e4, 1) if mv else None,
                         pe_ttm=pe, pb=pb, ps_ttm=ps, dv_ratio=dv, quantile=q,
                         annual={y: fin[y] for y in years[-4:]},
                         latest_periods={e: fin[e] for e in latest_q})
    # 站点模块里的预测原文
    try:
        db = find_db()
        ok, blocks, _m, err = execute_sql(
            db, "SELECT m.stock_code, b.data_json FROM module_blocks b "
                "JOIN stock_modules m ON b.module_id=m.id WHERE m.module_key='valuation'")
        if ok:
            for b in blocks:
                c = b['stock_code']
                if c not in out:
                    continue
                txt = b['data_json'] or ''
                hits = [mm.group(0)[:60] for mm in PAT.finditer(txt)]
                out[c].setdefault('site_pred', []).extend(hits)
        else:
            print('站点模块读取失败: %s' % err, file=sys.stderr)
    except Exception as e:
        print('站点模块读取异常: %s' % e, file=sys.stderr)

    # 券商一致预期（tushare report_rc，带缓存与限频处理）
    try:
        rc = rc_for(codes, os.path.abspath(args.rc_cache))
        for code in codes:
            if code in out:
                out[code]['rc'] = rc.get(code) or {}
    except Exception as e:
        print('券商预期获取失败: %s' % e, file=sys.stderr)

    # 人类可读
    for code in codes:
        d = out.get(code)
        if not d:
            continue
        if d.get('error'):
            print('【%s %s】%s' % (code, d.get('name', ''), d['error']))
            continue
        print('=' * 78)
        print('【%s %s】现价 %s 元 | 总市值 %s 亿 | PE(TTM) %s | PB %s | PS %s' % (
            code, d['name'], d['close'], d['total_mv_yi'],
            round(d['pe_ttm'], 2) if d['pe_ttm'] else '—',
            round(d['pb'], 2) if d['pb'] else '—', round(d['ps_ttm'], 2) if d['ps_ttm'] else '—'))
        for col, lbl in [('pe_ttm', 'PE'), ('pb', 'PB'), ('ps_ttm', 'PS')]:
            v = d['quantile'][col]
            if v['p50']:
                print('   %s 近三年：20%%分位 %.1f | 中位 %.1f | 80%%分位 %.1f（区间 %.1f~%.1f）'
                      % (lbl, v['p20'], v['p50'], v['p80'], v['lo'], v['hi']))
        print('   年报：' + ' | '.join('%s 净利%s亿/营收%s亿' % (y, a['ni'], a['rev'])
                                     for y, a in d['annual'].items()))
        print('   最新期：' + ' | '.join('%s 净利%s亿/营收%s亿' % (e, a['ni'], a['rev'])
                                      for e, a in sorted(d['latest_periods'].items())))
        if d.get('rc'):
            print('   券商一致预期：' + ' | '.join(
                '%sE %s亿(%d家, %s~%s)' % (y, a['med'], a['n'], a['lo'], a['hi']) for y, a in d['rc'].items()))
        if d.get('site_pred'):
            print('   站点模块写的：' + ' ;; '.join(d['site_pred']))

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
        print('\nJSON 已写入 %s' % args.json)


if __name__ == '__main__':
    main()
