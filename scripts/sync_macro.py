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
DAILY_LOOKBACK_DAYS = 400  # 滚动窗口：够页面画 250 点趋势，也不让 D1 无限膨胀（2026-09-16 由 30 调大）

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
    """日频指标 → (trade_date, indicator, value, unit)。

    单位统一成页面好读的口径：Shibor 隔夜 %、两融余额 亿元、北向净买 亿元、
    布伦特/WTI 美元/桶、美债 10Y/2Y %、离岸人民币 元。
    """
    out = []
    # 外盘原油（oil_global 的日期是 ISO 格式 2026-09-16，与 tushare 的 YYYYMMDD 不同）
    since_iso = '0000-00-00' if since == '00000000' else f'{since[:4]}-{since[4:6]}-{since[6:8]}'
    for symbol, indicator in (('BRENT', '布伦特原油'), ('WTI', 'WTI原油')):
        for date, close in conn.execute(
                'SELECT date, close FROM oil_global WHERE symbol = ? AND date >= ? ORDER BY date',
                (symbol, since_iso)):
            if close is not None:
                out.append((date.replace('-', ''), indicator, float(close), '美元/桶'))
    for date, y10, y2 in conn.execute(
            'SELECT date, y10, y2 FROM us_tycr WHERE date >= ? ORDER BY date', (since,)):
        if y10 is not None:
            out.append((date, '美债10Y', float(y10), '%'))
        if y2 is not None:
            out.append((date, '美债2Y', float(y2), '%'))
    for date, cnh in conn.execute(
            'SELECT trade_date, bid_close FROM fx_daily WHERE trade_date >= ? ORDER BY trade_date', (since,)):
        if cnh is not None:
            out.append((date, '离岸人民币', float(cnh), ''))
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


# ---- 框架条件变量体检（文章《产业投资框架》第 1 节定义 + 宏观页自测补充；2026-09-16 新增）----
COND_COLS = ['cond_key', 'title', 'target_text', 'current_text', 'status_kind',
             'status_text', 'source', 'source_kind', 'note', 'sort_order', 'updated_at']
MANUAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'macro_manual.json')
OIL_LEVEL = 95.0          # 场景 B 的油价阈值（美元/桶，布伦特）
OIL_STREAK_TARGET = 30    # 场景 B 要求的连续交易日数


def load_manual():
    """读手工录入的外部事实（库内无数据源的部分：美联储政策、美国 CPI 等）。

    文件缺失只告警不中断——体检卡少几行"手工项"可以接受，整体同步不能失败。
    """
    if not os.path.isfile(MANUAL_PATH):
        print(f'[warn] 缺手工事实文件 {MANUAL_PATH}，体检卡将缺少美联储/美国通胀项')
        return {}
    with open(MANUAL_PATH, encoding='utf-8') as f:
        return json.load(f)


def condition_rows(conn, now):
    """生成「框架条件变量体检」行 —— 每条 = 条件定义 + 当前实测 + 状态 + 数据来源。"""
    manual = load_manual()
    rows = []

    def add(key, title, target, current, kind, status, source, source_kind, note, order):
        rows.append((key, title, target, current, kind, status, source, source_kind, note, order, now))

    # ① 油价（场景 B 的触发条件：布伦特连续 ≥30 个交易日站稳 95 美元）
    oil = conn.execute("SELECT date, close FROM oil_global WHERE symbol='BRENT' ORDER BY date DESC").fetchall()
    if oil:
        streak = 0
        for _d, c in oil:
            if c is not None and float(c) >= OIL_LEVEL:
                streak += 1
            else:
                break
        latest_d, latest_c = oil[0]
        last30 = [float(c) for _d, c in oil[:30] if c is not None]
        since = oil[streak - 1][0] if streak else '—'
        kind = 'ok' if streak >= OIL_STREAK_TARGET else 'warn'
        add('oil_30d_95', '布伦特油价持续',
            f'连续 ≥{OIL_STREAK_TARGET} 个交易日站稳 {OIL_LEVEL:.0f} 美元 → 场景 B（转加息通道）',
            f'已连续 {streak} 个交易日 ≥{OIL_LEVEL:.0f}（{since} 起）；最新 {latest_c:.2f} 美元（{latest_d}）',
            kind, ('已触发' if kind == 'ok' else f'未触发（{streak}/{OIL_STREAK_TARGET}）'),
            '新浪外盘日线 oil_global（每日自动）', 'auto',
            f'近 30 个交易日区间 {min(last30):.2f}–{max(last30):.2f}；8 月低点 78.72 → 现价 +37%', 1)

    # ② 美联储方向（美债收益率曲线逐日上行 = 市场在定价更高利率，而非降息）
    fed = manual.get('fed_policy', {})
    tycr = conn.execute('SELECT date, y2, y10 FROM us_tycr ORDER BY date DESC LIMIT 1').fetchone()
    ymin, ymax = conn.execute(
        "SELECT MIN(y10), MAX(y10) FROM us_tycr WHERE date LIKE ?", (now[:4] + '%',)).fetchone()
    if tycr:
        add('fed_direction', '美联储方向（降息 vs 加息）',
            '文章原设定：预防式降息通道延续；反之为"跳出降息框架"进入加息通道',
            f'10Y 美债 {tycr[2]:.2f}%、2Y {tycr[1]:.2f}%（{tycr[0]}），年内 10Y 从 {ymin:.2f} 升到 {ymax:.2f}；'
            + (fed.get('text', '政策利率口径见手工项') ),
            'bad', '已偏离（降息通道已停）',
            f'tushare us_tycr（每日自动）＋{fed.get("source", "公开新闻")}', 'auto',
            '美债收益率单边上行＝市场在定价更高利率：与"降息"定性直接冲突', 2)

    # ③ 会议定价（手工项：库内无利率期货数据源）
    meeting = manual.get('fed_meeting', {})
    if meeting:
        add('fed_meeting_odds', '本次会议定价',
            '9 月 FOMC 加息 / 降息 / 按兵不动',
            meeting.get('text', ''), 'warn', '会前定价（决议前）',
            meeting.get('source', '公开新闻（手工录入）'), 'manual',
            f'手工项，as_of={meeting.get("as_of", "—")}；决议公布后需更新', 3)

    # ④ 通胀（预防式降息的前提是"通胀可控"）
    cpi = manual.get('us_cpi', {})
    ppi = conn.execute('SELECT month, ppi_yoy FROM cn_ppi ORDER BY month DESC LIMIT 1').fetchone()
    cn_cpi = conn.execute('SELECT month, nt_yoy FROM cn_cpi ORDER BY month DESC LIMIT 1').fetchone()
    if ppi and cn_cpi:
        add('inflation', '通胀是否可控（预防式降息前提）',
            '国内 PPI/CPI + 美国 CPI：通胀受控 → 降息前提成立',
            f'国内 PPI 同比 +{ppi[1]:.1f}%、CPI 同比 +{cn_cpi[1]:.1f}%（{ppi[0]}）；'
            + (cpi.get('text', '美国口径见手工项') ),
            'warn', '能源推升',
            f'tushare cn_ppi/cn_cpi（每月自动）＋{cpi.get("source", "公开新闻")}', 'auto',
            'PPI 同比转正 + 美国能源分项走高 = 油价正沿通胀传导', 4)

    # ⑤ 北向资金回流（文章传导链里唯一与国内数据相接的接口）
    nb = conn.execute('SELECT trade_date, north_money / 1e4 FROM moneyflow_hsgt ORDER BY trade_date DESC LIMIT 20').fetchall()
    if nb:
        total = sum(float(v) for _d, v in nb)
        last10 = [float(v) for _d, v in nb[:10]]
        add('northbound', '北向资金回流（传导链接口）',
            '美债利率下行 → 人民币升值预期 → 北向回流 A 股',
            f'近 {len(nb)} 个交易日累计净流入 {total:+.0f} 亿元；近 10 日每天 {min(last10):+.1f}~{max(last10):+.1f} 亿元',
            'ok', '成立',
            'tushare moneyflow_hsgt（每日自动）', 'auto',
            '文章链条中段（美债利率）已反向，但资金确实在回流 → 外部松 vs 内部弱的反差', 5)

    # ⑥ 离岸人民币（传导链中段变量）
    cnh = conn.execute('SELECT trade_date, bid_close FROM fx_daily ORDER BY trade_date DESC LIMIT 1').fetchone()
    rng = conn.execute(
        'SELECT MIN(bid_close), MAX(bid_close) FROM (SELECT bid_close FROM fx_daily ORDER BY trade_date DESC LIMIT 250)').fetchone()
    if cnh:
        add('cnh', '离岸人民币汇率',
            '人民币升值预期（北向回流的前置条件）',
            f'USDCNH {cnh[1]:.4f}（{cnh[0]}）；近 250 个交易日区间 {rng[0]:.4f}–{rng[1]:.4f}',
            'ok', '偏强（接近一年最强势）',
            'tushare fx_daily（每日自动）', 'auto',
            '人民币偏强 → 与文章"美元走强、A股承压"的场景 B 后半段暂不吻合', 6)

    # ⑦ 国内需求（文章未覆盖，宏观页自测：外部流动性友好是否被内部承接）
    sf = conn.execute(
        "SELECT date, value_num, fore_num FROM macro_calendar WHERE event LIKE '中国社会融资%' "
        'AND value IS NOT NULL ORDER BY date DESC LIMIT 1').fetchone()
    ln = conn.execute(
        "SELECT date, value_num, fore_num FROM macro_calendar WHERE event LIKE '中国新增人民币贷款%' "
        'AND value IS NOT NULL ORDER BY date DESC LIMIT 1').fetchone()
    m = conn.execute('SELECT month, m1_yoy, m2_yoy FROM cn_m ORDER BY month DESC LIMIT 1').fetchone()
    if sf and ln and m:
        add('domestic_demand', '国内需求（外部流动性能否被承接）',
            '社融/信贷/货币剪刀差：内需与货币活化程度',
            f'社融 {sf[1] / 1e12:.2f} 万亿 vs 预期 {sf[2] / 1e12:.2f} 万亿（{(sf[1] - sf[2]) / 1e8:+,.0f} 亿元）；'
            f'信贷 {ln[1] / 1e8:.0f} 亿 vs 预期 {ln[2] / 1e8:.0f} 亿（{(ln[1] - ln[2]) / 1e8:+,.0f} 亿元）；'
            f'M1−M2 剪刀差 {m[1] - m[2]:+.1f} 个百分点（{m[0]}）',
            'bad', '弱（外部松、内部弱）',
            'tushare macro_calendar / cn_m（每月自动）', 'auto',
            '钱躺着不动 + 信贷断崖：外资回流与内需弱同时成立，只看一边都会看偏', 7)
    return rows


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
        ('macro_conditions 条件数与状态分布',
         'SELECT COUNT(*) n, GROUP_CONCAT(status_kind) kinds FROM macro_conditions'),
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
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cond = condition_rows(conn, now)   # 条件变量体检（依赖 now 作 updated_at）
    conn.close()

    header = [f'-- 宏观数据（sync_macro.py 生成 {now}）',
              '-- 源：stock-analytics macro_calendar/macro_series/macro_daily/oil_global/us_tycr/fx_daily',
              '--    （tushare 为主，外盘原油走新浪全球期货日线；手工项见 scripts/macro_manual.json）']
    stmts = []
    stmts += insert_stmts('macro_calendar', CAL_COLS, cal, ['date', 'time', 'event'])
    stmts += insert_stmts('macro_series', SERIES_COLS, series, ['month', 'indicator'])
    stmts += insert_stmts('macro_daily', DAILY_COLS, daily, ['trade_date', 'indicator'])
    stmts += insert_stmts('macro_conditions', COND_COLS, cond, ['cond_key'])

    # 注释块放在文件头且**不单独成句**（否则 cf_d1 exec 会把注释当语句执行）
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(header) + '\n' + ';\n'.join(stmts) + ';\n')
    print(f'SQL 已写出：{args.out}（{len(stmts)} 条语句）')
    print(f'  日历 {len(cal)} 行（其中未来排期 {sum(1 for r in cal if r[0] > now[:10].replace("-", ""))} 行）'
          f' ｜ 序列 {len(series)} 行 ｜ 日频 {len(daily)} 行（since={since}）｜ 条件变量 {len(cond)} 条')

    if args.exec:
        db, total = exec_stmts(stmts)
        print(f'已写入 D1，累计 rows_changed={total}（⚠️ D1 对 upsert 恒回报 0，以回读为准）')
        verify(db)


if __name__ == '__main__':
    main()
