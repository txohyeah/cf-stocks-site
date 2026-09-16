#!/usr/bin/env python3
"""宏观数据同步：stock-analytics sqlite → 线上 D1（宏观页 /macro 的数据源）。

用法：
  python3 scripts/sync_macro.py                        # 只生成 SQL 到 data/macro_sync.sql
  python3 scripts/sync_macro.py --exec                 # 生成并写入 D1（日频仅近 30 天）
  python3 scripts/sync_macro.py --exec --daily-full    # 首次上线：日频全量灌历史

三张表（DDL 见 schema.sql）：
  macro_calendar  数据发布日历（含未来排期）+ 参照系（同比/近 12 期分位/历年同期均值）——**全量 UPSERT**
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
import re
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import STOCK_ANALYTICS_DB  # noqa: E402  （本机私有路径，不入版本控制）

OUT = os.path.join(ROOT, 'data', 'macro_sync.sql')
BATCH = 100  # D1 单条语句有长度上限（SQLITE_TOOBIG），分批
DAILY_LOOKBACK_DAYS = 400  # 滚动窗口：够页面画 250 点趋势，也不让 D1 无限膨胀（2026-09-16 由 30 调大）

BASE_CAL_COLS = ['date', 'time', 'event', 'value', 'fore_value', 'pre_value',
                 'value_num', 'fore_num', 'pre_num', 'surprise', 'unit']
# 参照系列（2026-09-16 新增）：让"预期差"之外多一个**绝对水平**的判断依据。
#   ref_yoy      去年同期值（按"数据月份"对齐，不按发布日期）
#   ref_yoy_diff 本期 − 去年同期（金额口径=金额差；% 口径=百分点差）
#   ref_yoy_pct  变化率%（仅金额口径有意义；% 口径留空，避免"同比的同比"）
#   ref_avg5     历年同期均值（前 1~5 年同月，≥3 年才给）
#   pct_rank     近 12 期分位：升序里"≤本期"的期数 ÷ 期数（0~1；越大越强）
#   pct_rank_n   分位窗口实际期数（<6 期不给分位，宁缺勿假）
# ⚠️ 明确**不做环比**（mom）：社融/信贷/CPI 季节性极强（1 月天量、7 月低），
#    环比会系统性误导；要拆季节性看 ref_avg5。
CAL_COLS = BASE_CAL_COLS + ['ref_yoy', 'ref_yoy_diff', 'ref_yoy_pct',
                            'ref_avg5', 'ref_avg5_n', 'pct_rank', 'pct_rank_n']

# 事件名末尾的月份后缀（"中国CPI年率(%)(年度)(八月)"）——同一个指标跨年只能靠它合并
_MONTH_SUFFIX_RE = re.compile(r'\((一月|二月|三月|四月|五月|六月|七月|八月|九月|十月|十一月|十二月)\)\s*$')
_CN_MONTHS = {'一月': 1, '二月': 2, '三月': 3, '四月': 4, '五月': 5, '六月': 6,
              '七月': 7, '八月': 8, '九月': 9, '十月': 10, '十一月': 11, '十二月': 12}
PCT_RANK_WINDOW = 12   # 分位窗口：近 12 期
PCT_RANK_MIN = 6       # 窗口少于 6 期不给分位
REF_YOY_TOL_DAYS = 35  # 去年同期按数据月份匹配失败时，退化为发布日期匹配的容差
REF_AVG_YEARS = 5      # 历年同期均值回溯年数
REF_AVG_MIN = 3        # 至少匹配到几年才给均值
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


def series_key(event):
    """指标名归一：剥掉事件名末尾的月份后缀，跨年才能合成一条序列。

    '中国CPI年率(%)(年度)(八月)' → '中国CPI年率(%)(年度)'
    实测（2026-09-16）归一后 41 条序列，社融/信贷/CPI/PPI/M2/PMI 等主序列都干净。
    """
    return _MONTH_SUFFIX_RE.sub('', str(event)).strip()


def data_month(date, event):
    """这次发布对应的**数据月份** 'YYYYMM'（同比/同月均值按它对齐，比发布日期稳）。

    带月份后缀的用后缀（跨年按"数据月不能晚于发布月"回推一年）；
    不带后缀的老行（2019-2021 那批）按发布月 −1 推。
    """
    y, m = int(date[:4]), int(date[4:6])
    hit = _MONTH_SUFFIX_RE.search(str(event))
    if hit:
        dm = _CN_MONTHS[hit.group(1)]
        if dm > m:
            y -= 1
        return f'{y:04d}{dm:02d}'
    if m == 1:
        return f'{y - 1:04d}12'
    return f'{y:04d}{m - 1:02d}'


def derive_refs(rows):
    """按序列算出每行的参照系 → {(date, time, event): (ref_yoy, diff, pct, avg5, avg5_n, rank, rank_n)}。

    只对"有实际值"的行算；分位窗口只用该行**当时已公布**的期数（trailing），
    所以历史行是"当时的视角"，最新行自然就是"近 12 期"。
    """
    from collections import defaultdict

    series = defaultdict(dict)   # 序列 key → {数据月份: (发布日期, 值, 单位)}
    for r in rows:
        date, event, vnum = r[0], r[2], r[6]
        if vnum is None:
            continue
        k, dm = series_key(event), data_month(date, event)
        cur = series[k].get(dm)
        # 同一数据月可能有两行（老的无后缀行 + 新的带后缀行；2026-09-16 实测 5 条序列有）
        # → 每数据月只留一条，冲突时保留发布日期更早的
        if cur is None or date < cur[0]:
            series[k][dm] = (date, float(vnum), r[10])

    seq_of = {k: sorted(v.items()) for k, v in series.items()}   # [(数据月份, (日期, 值, 单位))]

    ref_map = {}
    for k, seq in seq_of.items():
        months = [dm for dm, _ in seq]
        vals = [t[1][1] for t in seq]
        idx = {dm: i for i, dm in enumerate(months)}
        for i, (dm, (date, val, unit)) in enumerate(seq):
            yr, mo = int(dm[:4]), dm[4:]
            prev_m = f'{yr - 1:04d}{mo}'
            ref_yoy = vals[idx[prev_m]] if prev_m in idx else None
            hist = [vals[idx[f'{yr - k:04d}{mo}']] for k in range(1, REF_AVG_YEARS + 1)
                    if f'{yr - k:04d}{mo}' in idx]
            avg5 = (sum(hist) / len(hist)) if len(hist) >= REF_AVG_MIN else None
            win = vals[max(0, i - PCT_RANK_WINDOW + 1): i + 1]
            rank = (sum(1 for x in win if x <= val) / len(win)) if len(win) >= PCT_RANK_MIN else None
            diff = None if ref_yoy is None else val - ref_yoy
            pct = ((val - ref_yoy) / abs(ref_yoy) * 100
                   if (ref_yoy not in (None, 0) and unit != '%') else None)
            ref_map[(date, k)] = (ref_yoy, diff, pct, avg5, len(hist), rank, len(win))

    return {(r[0], r[1], r[2]): ref_map.get((r[0], series_key(r[2])))
            for r in rows if r[6] is not None}


def calendar_rows(conn):
    """发布日历（基础列 + 现算的参照系列）。"""
    sql = f"SELECT {', '.join(BASE_CAL_COLS)} FROM macro_calendar ORDER BY date, time, event"
    rows = list(conn.execute(sql))
    refs = derive_refs(rows)
    return [tuple(r) + (refs.get((r[0], r[1], r[2])) or (None,) * 7) for r in rows]


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
            + (fed.get('text', '政策利率口径见手工项')),
            # kind/status/note 自 2026-09-16 起从 macro_manual.json 读（此前是写死在这里的）——
            # 加息落地后只改 JSON 即可，不必动代码；kind='hike' 会驱动置顶「当前定性」换挡
            fed.get('kind', 'bad'), fed.get('status', '已偏离（降息通道已停）'),
            f'tushare us_tycr（每日自动）＋{fed.get("source", "公开新闻")}', 'auto',
            fed.get('note', '美债收益率单边上行＝市场在定价更高利率：与"降息"定性直接冲突'), 2)

    # ③ 会议定价（手工项：库内无利率期货数据源；决议公布后改 macro_manual.json 的 fed_meeting）
    meeting = manual.get('fed_meeting', {})
    if meeting:
        add('fed_meeting_odds', '本次会议定价',
            '9 月 FOMC 加息 / 降息 / 按兵不动',
            meeting.get('text', ''),
            meeting.get('kind', 'warn'), meeting.get('status', '会前定价（决议前）'),
            meeting.get('source', '公开新闻（手工录入）'), 'manual',
            meeting.get('note', f'手工项，as_of={meeting.get("as_of", "—")}；决议公布后需更新'), 3)

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


# ---- 当前宏观定性（2026-09-16 新增）----
# 承接原文章《产业投资框架》§1.3「当前判断」——文章从此只讲方法论、不随行情改写，
# "现在处在哪一层"由本规则层每天重算，**只在定性变化时**往 macro_notes(kind='regime') 留一条历史。
REGIME_CHECKS = ['oil_30d_95', 'fed_direction', 'fed_meeting_odds', 'inflation',
                 'northbound', 'cnh', 'domestic_demand']


def regime_text(conn, cond, now):
    """由体检条件推「当前定性」→ (定性一句话, 变更依据快照 md, 数据口径日期)。

    ⚠️ 定性文本必须**在同一档位内保持稳定**（不写数字/日期），否则每次同步都会被判成"变了"而刷记录。
    数字放"依据快照"里（记的是变更当时的快照）；日常的实时数字看体检卡。
    """
    st = {r[0]: r for r in cond}          # cond_key -> (key, title, target, current, kind, status, source, source_kind, note, order, updated)
    oil = conn.execute("SELECT date, close FROM oil_global WHERE symbol='BRENT' ORDER BY date DESC").fetchall()
    streak = 0
    for _d, c in oil:
        if c is not None and float(c) >= OIL_LEVEL:
            streak += 1
        else:
            break
    fed = st.get('fed_direction')
    fed_kind = fed[4] if fed else ''
    if fed_kind == 'hike':
        # 加息真落地了 → 不再等油价条件（场景 B 是"降息暂停 → 转加息"的代理，真加息比代理更直接）
        title = '已进入加息通道（加息已落地，不再等油价条件）'
    elif streak >= OIL_STREAK_TARGET:
        title = '框架已切换：场景 B 成立（降息暂停 → 转加息通道）'
    elif fed_kind == 'bad':
        title = '已跳出降息框架（降息通道已停，转加息定价中）'
    elif fed_kind == 'ok':
        title = '预防式降息通道延续（场景 A）'
    else:
        title = '降息通道尚在，但有条件已偏离'

    oil_txt = (f'布伦特 {oil[0][1]:.2f} 美元（{oil[0][0]}），连续 ≥{OIL_LEVEL:.0f} 已 '
               f'{streak}/{OIL_STREAK_TARGET} 个交易日') if oil else '油数据缺失'
    lines = [f'**定量依据（{now[:10]} 快照）**：{oil_txt}。', '']
    for k in REGIME_CHECKS:
        r = st.get(k)
        if r:
            lines.append(f'- **{r[1]}**：{r[5]}')
    lines += ['', '**口径**：定性由框架条件自动判定（scripts/sync_macro.py），只在变化时留档；'
                  '逐条条件的每日实测见下方「框架条件变量体检」，'
                  '每次数据发布后的分析结论见「解读笔记」。']
    # as_of 统一成 YYYYMMDD（与页面上其它口径一致；oil_global 的 date 是 ISO 带横线）
    as_of = (oil[0][0] if oil else now[:10]).replace('-', '')
    return title, '\n'.join(lines), as_of


def sync_regime(title, body, as_of, now, out_path=None):
    """只在**定性文本变化**时新增一条 macro_notes(kind='regime')；幂等。

    尊重人工：若最新一条 regime 是 source='human'，规则层不再覆盖（人工说了算）；
    source='manual' 表示历史归档快照，不阻挡规则层写入。
    """
    import cf_d1
    db = cf_d1.find_db()
    if not db:
        raise SystemExit('D1 不存在')

    ok, rows, _m, err = cf_d1.execute_sql(
        db, "SELECT note_date, title, source FROM macro_notes WHERE kind = 'regime' "
            'ORDER BY note_date DESC LIMIT 1')
    if not ok:
        print('[定性] 读最新条目失败：' + json.dumps(err, ensure_ascii=False)[:200])
        return
    latest = rows[0] if rows else None
    if latest and latest['title'] == title:
        print(f"[定性] 未变（{title}，自 {latest['note_date']}）→ 不写新记录")
        return
    if latest and latest['source'] == 'human':
        print(f"[定性] 最新一条是人工撰写（{latest['note_date']}），规则层不覆盖 → 不写")
        return

    note_date = now[:10].replace('-', '')
    row = [(note_date, 'regime', now, title, body, '', as_of, 'auto')]
    stmts = insert_stmts('macro_notes', NOTE_COLS, row, ['note_date', 'kind'])
    if out_path:
        with open(out_path, 'a', encoding='utf-8') as f:
            f.write('\n-- 当前宏观定性（只在定性变化时新增）\n')
            f.write(';\n'.join(stmts) + ';\n')
    for i, stmt in enumerate(stmts, 1):
        ok, _r, meta, err = cf_d1.execute_sql(db, stmt)
        if not ok:
            print(f'[定性FAIL] ' + json.dumps(err, ensure_ascii=False)[:300])
            return
    ok, rows, _m, err = cf_d1.execute_sql(
        db, "SELECT note_date, title, source, length(body_md) n FROM macro_notes "
            "WHERE kind = 'regime' ORDER BY note_date DESC")
    print(f"[定性] 写出新记录 → {title}")
    for r in (rows or []):
        print('   ', json.dumps(r, ensure_ascii=False))


# ---- 宏观 → 产业 传导（2026-09-16 新增；规则表在 scripts/macro_industry.json，改规则不用改代码）----
IND_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'macro_industry.json')
IND_COLS = ['industry_id', 'name', 'link', 'state_kind', 'state_text',
            'favorable', 'unfavorable', 'drivers_json', 'updated_at']

# macro_notes（解读笔记 + 当前定性）：kind='regime' 的行是"当前定性"的历史，
# 由 sync_regime() 只在定性变化时新增；其余 kind（release/weekly）由 agent cron 写。
NOTE_COLS = ['note_date', 'kind', 'created_at', 'title', 'body_md', 'covered', 'as_of', 'source']

# 发布日历类指标的"阈值单位"：JSON 里的阈值按这个口径写（社融用万亿、信贷用亿、比率用原值）
CAL_SCALE = {
    '中国社会融资规模': (1e12, '万亿'),
    '中国新增人民币贷款': (1e8, '亿'),
}


def load_industry_map():
    with open(IND_PATH, encoding='utf-8') as f:
        return json.load(f).get('industries', [])


def metric_values(conn):
    """所有可测驱动指标 → {metric: (数值, 展示文案, 日期)}。数值单位与 JSON 阈值口径一致。"""
    m = {}
    r = conn.execute("SELECT date, close FROM oil_global WHERE symbol='BRENT' ORDER BY date DESC LIMIT 1").fetchone()
    if r:
        m['brent'] = (float(r[1]), f'{r[1]:.2f} 美元/桶', r[0])
        streak, since = 0, None
        for d, c in conn.execute("SELECT date, close FROM oil_global WHERE symbol='BRENT' ORDER BY date DESC"):
            if c is not None and float(c) >= 95:
                streak += 1
                since = d
            else:
                break
        m['brent_streak95'] = (streak, f'连续 {streak} 个交易日 ≥95 美元（{since} 起）', r[0])
    r = conn.execute('SELECT date, y10, y2 FROM us_tycr ORDER BY date DESC LIMIT 1').fetchone()
    if r:
        if r[1] is not None:
            m['us10y'] = (float(r[1]), f'{r[1]:.2f}%', r[0])
        if r[2] is not None:
            m['us2y'] = (float(r[2]), f'{r[2]:.2f}%', r[0])
    r = conn.execute('SELECT trade_date, bid_close FROM fx_daily ORDER BY trade_date DESC LIMIT 1').fetchone()
    if r:
        m['cnh'] = (float(r[1]), f'{r[1]:.4f}', r[0])
    r = conn.execute('SELECT date, "on" FROM shibor ORDER BY date DESC LIMIT 1').fetchone()
    if r:
        m['shibor_on'] = (float(r[1]), f'{r[1]:.2f}%', r[0])
    r = conn.execute('SELECT trade_date, SUM(rzye + rqye) / 1e12 FROM margin '
                     'GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1').fetchone()
    if r:
        m['margin_total'] = (float(r[1]), f'{r[1]:.2f} 万亿', r[0])
    r = conn.execute('SELECT COUNT(*), SUM(north_money) / 1e4, MAX(trade_date) FROM ('
                     'SELECT trade_date, north_money FROM moneyflow_hsgt ORDER BY trade_date DESC LIMIT 20)').fetchone()
    if r and r[0]:
        m['north20'] = (float(r[1]), f'近 {r[0]} 日累计 {r[1]:+,.0f} 亿元', r[2])
    r = conn.execute('SELECT month, m1_yoy - m2_yoy FROM cn_m ORDER BY month DESC LIMIT 1').fetchone()
    if r:
        m['series:M1M2剪刀差'] = (float(r[1]), f'{r[1]:+.1f} 个百分点（{r[0]}）', r[0])
    return m


def cal_metric(conn, kw):
    """发布日历里某事件最新一次公布值 → (数值, 文案, 日期)，单位按 CAL_SCALE 换算。"""
    r = conn.execute(
        "SELECT date, value_num, unit FROM macro_calendar WHERE event LIKE ? AND value IS NOT NULL "
        'ORDER BY date DESC LIMIT 1', (kw + '%',)).fetchone()
    if not r:
        return None
    scale, unit = CAL_SCALE.get(kw, (1.0, r[2]))
    v = float(r[1]) / scale
    if unit == '%':
        text = f'{v:.2f}%'
    elif unit == '万亿':
        text = f'{v:.2f} 万亿'
    elif unit == '亿':
        text = f'{v:,.0f} 亿'
    elif unit:
        text = f'{v:,.2f} {unit}'
    else:
        text = f'{v:,.2f}'
    return (v, text, r[0])


def industry_rows(conn, now):
    """按规则表评估每个产业的宏观顺风/逆风 → macro_industry_state 行。"""
    m = metric_values(conn)
    rows = []
    for ind in load_industry_map():
        drivers, fav, unfav = [], 0, 0
        for d in ind.get('drivers', []):
            metric = d['metric']
            hit = m.get(metric) or (cal_metric(conn, metric[4:]) if metric.startswith('cal:') else None)
            if not hit:
                drivers.append({'label': d.get('label', metric), 'value_text': '无数据', 'side': 'unknown',
                                'note': d.get('note', '')})
                continue
            v, text, date = hit
            thr, band = float(d['threshold']), float(d.get('neutral', 0) or 0)
            if band and abs(v - thr) <= band:
                side = 'neutral'
            elif d['favor'] == 'above':
                side = 'favorable' if v >= thr else 'unfavorable'
            else:
                side = 'favorable' if v <= thr else 'unfavorable'
            fav += side == 'favorable'
            unfav += side == 'unfavorable'
            cmp_text = ('≥' if d['favor'] == 'above' else '≤') + f'{thr:g}'
            drivers.append({'label': d.get('label', metric), 'value_text': text,
                            'side': side, 'rule': cmp_text, 'note': d.get('note', ''), 'date': date})
        if fav > unfav:
            kind, state = 'favorable', f'偏顺风（{fav} 顺 / {unfav} 逆）'
        elif unfav > fav:
            kind, state = 'unfavorable', f'偏逆风（{fav} 顺 / {unfav} 逆）'
        else:
            kind, state = 'mixed', f'分化（{fav} 顺 / {unfav} 逆）'
        rows.append((ind['id'], ind['name'], ind.get('link', ''), kind, state, fav, unfav,
                     json.dumps(drivers, ensure_ascii=False), now))
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
        ('参照系覆盖（有实际值的行中已算出分位/同比的行数）',
         'SELECT COUNT(*) filled, SUM(pct_rank IS NOT NULL) has_rank, SUM(ref_yoy IS NOT NULL) has_yoy, '
         'SUM(ref_avg5 IS NOT NULL) has_avg5 FROM macro_calendar WHERE value IS NOT NULL'),
        ('macro_industry_state 产业数与状态分布',
         'SELECT COUNT(*) n, GROUP_CONCAT(state_text) kinds FROM macro_industry_state'),
        ('当前宏观定性（macro_notes kind=regime 条数与最新一条）',
         "SELECT COUNT(*) n, MAX(note_date) latest FROM macro_notes WHERE kind = 'regime'"),
        ('最新定性文本',
         "SELECT note_date, title, source FROM macro_notes WHERE kind = 'regime' ORDER BY note_date DESC LIMIT 1"),
        ('最新社融的参照系（应：去年同期 + 分位 + 历年同期均值）',
         "SELECT date, pct_rank, pct_rank_n FROM macro_calendar WHERE event LIKE '中国社会融资规模%' "
         'AND value IS NOT NULL ORDER BY date DESC LIMIT 1'),
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
    ind = industry_rows(conn, now)     # 宏观 → 产业 传导（规则表 scripts/macro_industry.json）
    regime = regime_text(conn, cond, now)   # 当前定性（要读 analytics 连接 → 必须在 close 之前算）
    conn.close()

    header = [f'-- 宏观数据（sync_macro.py 生成 {now}）',
              '-- 源：stock-analytics macro_calendar/macro_series/macro_daily/oil_global/us_tycr/fx_daily',
              '--    （tushare 为主，外盘原油走新浪全球期货日线；手工项见 scripts/macro_manual.json）']
    stmts = []
    stmts += insert_stmts('macro_calendar', CAL_COLS, cal, ['date', 'time', 'event'])
    stmts += insert_stmts('macro_series', SERIES_COLS, series, ['month', 'indicator'])
    stmts += insert_stmts('macro_daily', DAILY_COLS, daily, ['trade_date', 'indicator'])
    stmts += insert_stmts('macro_conditions', COND_COLS, cond, ['cond_key'])
    stmts += insert_stmts('macro_industry_state', IND_COLS, ind, ['industry_id'])

    # 注释块放在文件头且**不单独成句**（否则 cf_d1 exec 会把注释当语句执行）
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(header) + '\n' + ';\n'.join(stmts) + ';\n')
    print(f'SQL 已写出：{args.out}（{len(stmts)} 条语句）')
    print(f'  日历 {len(cal)} 行（其中未来排期 {sum(1 for r in cal if r[0] > now[:10].replace("-", ""))} 行）'
          f' ｜ 序列 {len(series)} 行 ｜ 日频 {len(daily)} 行（since={since}）｜ 条件变量 {len(cond)} 条')
    print(f'  当前定性：{regime[0]}')

    if args.exec:
        db, total = exec_stmts(stmts)
        print(f'已写入 D1，累计 rows_changed={total}（⚠️ D1 对 upsert 恒回报 0，以回读为准）')
        sync_regime(*regime, now, args.out)   # 定性层：只在文本变化时新增一条历史
        verify(db)                            # 回读核对放最后，让"当前定性"那一项反映本次结果


if __name__ == '__main__':
    main()
