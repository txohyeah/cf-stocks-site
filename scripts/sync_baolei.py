#!/usr/bin/env python3
"""暴雷检查数据同步：stock-analytics baolei → D1 risk_checks

流程：
  1. 读**线上 D1** `stocks` 表（tracked=1）拿站点全部标的（新增标的自动纳入）；
     也可用 `--codes` 只处理指定标的（单只收录补数据用）
  2. 调 stock-analytics CLI `baolei`（**一次调用全部 code**，bulk_fetch 只跑一次）
     - stdout 末行 JSON  → 综合评级 / 五雷区灯色 / 深度检查 / 触发项
     - --report 文本报告 → 补五雷区逐项说明（JSON payload 不含 detail 字段）
  3. 生成 SQL（**只动 risk_checks 表**，不碰 stock_modules 内容块体系）
     - 默认：**增量 UPSERT**（ON CONFLICT DO UPDATE），只覆盖本次涉及的标的
     - `--all`：全量重建（先 DELETE 全表再插入），仅刷新全部评级时用

用法：
  python3 scripts/sync_baolei.py                      # 全量刷新：只生成 SQL
  python3 scripts/sync_baolei.py --exec               # 全量刷新：生成后写 D1（增量 UPSERT）
  python3 scripts/sync_baolei.py --all --exec         # 全量重建（DELETE + INSERT）
  python3 scripts/sync_baolei.py --codes 600114.SH --exec   # 只补一只（增量）

被 add_stock.py 复用：收录新票时自动调 sync_codes([code], exec_=True)。

约定（勿改）：
  - 只读 CLI 的 stdout，不解析 stderr 进度日志
  - JSON 解析失败即中止，不静默降级（宁可报错也不写半成品数据）
  - 默认不得 DELETE 整表（除显式 --all）；--all 与 --limit/--codes 互斥
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))
ARCHIVE = os.path.join(WORKSPACE, 'media', 'u4_site_archive')  # 历史快照，仅备查（不再作为标的池来源）
ANALYTICS = '/home/application/stock-analytics'
ANALYTICS_PY = os.path.join(ANALYTICS, 'venv', 'bin', 'python')
OUT = os.path.join(ROOT, 'data', 'risk_seed.sql')
REPORT_TMP = os.path.join(ROOT, 'data', '.baolei_report.md')

ZONE_TAGS = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4}
ZONE_RE = re.compile(r'^-\s*\[(绿|黄|红)\]\s*雷区([零一二三四])[^：]*：(.*)$')
STOCK_RE = re.compile(r'^#\s+(\S+)\s+(.*?)\s+排雷报告\s*$')

# 报告行存在但冒号后为空时的兜底文案（仅当该雷区行**确实存在却无说明**时使用）。
# 雷区三：baolei 在 balancesheet.goodwill 为 NULL（公司无商誉科目）时不写说明，
# 页面会显示空白格 → 补"无商誉（商誉科目为空）"，灯色恒为绿。
ZONE_FALLBACK = {3: '无商誉（商誉科目为空）'}


def q(s):
    return str(s).replace("'", "''")


def site_codes():
    """站点标的池：读**线上 D1** `stocks` 表（tracked=1）。

    2026-09-15 修正：原实现读冻结快照 media/u4_site_archive/api_stocks.json（145 只），
    导致此后新收录的标的永远进不了扫描（实测 165 只站点标的里缺 20 只）。
    改为以线上库为准，新增标的自动纳入；D1 不可用/表空即报错中止，不静默降级。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cf_d1
    db = cf_d1.find_db()
    if not db:
        raise SystemExit('未找到 D1 数据库，无法取站点标的池')
    ok, rows, _meta, errors = cf_d1.execute_sql(
        db, 'SELECT code FROM stocks WHERE tracked = 1 ORDER BY code')
    if not ok:
        raise SystemExit('读 D1 stocks 失败: ' + json.dumps(errors, ensure_ascii=False))
    codes = [r['code'] for r in (rows or [])]
    if not codes:
        raise SystemExit('D1 stocks 表为空，拒绝继续（避免清空 risk_checks）')
    print(f'[codes] 站点标的池（D1 stocks, tracked=1）：{len(codes)} 只')
    return codes


def run_baolei(codes):
    """调 baolei CLI：返回 (json_results, zone_details)"""
    cmd = [ANALYTICS_PY, '-m', 'app.analytics.cli', 'baolei',
           '--codes', ','.join(codes), '--report', REPORT_TMP]
    print(f'[baolei] {len(codes)} 只，一次调用（bulk_fetch 全量加载，需耐心等待）...')
    p = subprocess.run(cmd, cwd=ANALYTICS, capture_output=True, text=True, timeout=3600)
    if p.returncode != 0:
        raise SystemExit(f'baolei 失败（退出码 {p.returncode}）:\n{(p.stderr or "")[-2000:]}')

    # ---- JSON：stdout 末行 ----
    payload = None
    for line in reversed((p.stdout or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            payload = json.loads(line)
            break
    if payload is None:
        raise SystemExit(f'未能从 stdout 解析 JSON，末尾输出:\n{(p.stdout or "")[-2000:]}')
    results = {r['ts_code']: r for r in payload.get('results', [])}

    # ---- 文本报告：补五雷区 detail ----
    zones = {}
    if os.path.exists(REPORT_TMP):
        cur = None
        with open(REPORT_TMP, encoding='utf-8') as f:
            for line in f:
                m = STOCK_RE.match(line.rstrip())
                if m:
                    cur = m.group(1)
                    zones.setdefault(cur, {})
                    continue
                if cur is None:
                    continue
                z = ZONE_RE.match(line.rstrip())
                if z:
                    zones[cur][ZONE_TAGS[z.group(2)]] = z.group(3).strip()
        os.remove(REPORT_TMP)
    return results, zones


def zone_rating(r):
    """结构风险评级：仅五雷区口径（审计/利润结构/现金流/商誉/业绩拐点），深度检查不参与。"""
    lights = [r.get(f'r{i}') for i in range(5)]
    if '红' in lights:
        return '高'
    return '中' if '黄' in lights else '低'


COLS = ('stock_code, rating, rating_zone, '
        'r0, r0_detail, r1, r1_detail, r2, r2_detail, r3, r3_detail, r4, r4_detail, '
        'deep_json, reasons, as_of, checked_at')
# 增量写入时覆盖的列（stock_code 是主键，不动）
UPD_COLS = ('rating', 'rating_zone', 'r0', 'r0_detail', 'r1', 'r1_detail', 'r2', 'r2_detail',
            'r3', 'r3_detail', 'r4', 'r4_detail', 'deep_json', 'reasons', 'as_of', 'checked_at')
BATCH = 20  # D1 单条语句有长度上限（SQLITE_TOOBIG），分批


def rows_of(results, zones):
    """baolei 结果 → SQL 行字面量列表（跳过无评级 = 无年报数据）。返回 (rows, skipped, now)"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    rows, skipped = [], 0
    for code in sorted(results):
        r = results[code]
        rating = r.get('rating')
        if not rating:
            skipped += 1
            continue
        zd = zones.get(code, {})
        # 五雷区：灯色取 JSON，说明优先取报告文本，兜底空值文案
        cells = []
        for i in range(5):
            light = r.get(f'r{i}', '') or ''
            detail = zd.get(i, '')
            if detail == '' and i in zd and i in ZONE_FALLBACK:
                detail = ZONE_FALLBACK[i]
            cells += [f"'{q(light)}'", f"'{q(detail)}'"]
        deep = json.dumps(r.get('deep_checks') or [], ensure_ascii=False)
        reasons = json.dumps(r.get('reasons') or [], ensure_ascii=False)
        as_of = ''
        rows.append(
            f"('{q(code)}', '{q(rating)}', '{q(zone_rating(r))}', {', '.join(cells)}, "
            f"'{q(deep)}', '{q(reasons)}', '{q(as_of)}', '{q(now)}')")
    return rows, skipped, now


def build_sql(results, zones, rebuild=False):
    """生成写入语句。

    rebuild=False（默认）：**增量 UPSERT** —— 只动本次涉及的行，其余行原样保留。
    rebuild=True（--all）：先 DELETE 全表再插入 —— 仅在刷新全部评级时用。
    """
    rows, skipped, now = rows_of(results, zones)
    mode = '全量重建（DELETE + INSERT）' if rebuild else '增量 UPSERT'
    stmts = ['-- 暴雷检查（自动排雷 · sync_baolei.py 生成）',
             f'-- 生成时间 {now} ｜ 数据源 stock-analytics baolei（tushare）｜ 模式：{mode}']
    if rebuild:
        stmts.append('DELETE FROM risk_checks;')
    else:
        stmts.append('-- 增量模式：无 DELETE，未涉及的标的保持原值')
    tail = ';'
    if not rebuild and rows:
        tail = '\nON CONFLICT(stock_code) DO UPDATE SET\n  ' + \
               ',\n  '.join(f'{c} = excluded.{c}' for c in UPD_COLS) + ';'
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        stmts.append(f'INSERT INTO risk_checks ({COLS}) VALUES\n' + ',\n'.join(chunk) + tail)
    return stmts, len(rows), skipped


def exec_stmts(stmts, db=None):
    """执行语句列表（跳过注释行）。返回各语句 rows_changed。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cf_d1
    db = db or cf_d1.find_db()
    if not db:
        raise SystemExit('D1 不存在')
    changed = []
    i = 0
    for stmt in stmts:
        if stmt.lstrip().startswith('--'):
            continue
        i += 1
        ok, _rows, meta, err = cf_d1.execute_sql(db, stmt)
        if not ok:
            raise SystemExit(f'[FAIL] 语句 {i}: ' + json.dumps(err, ensure_ascii=False)[:500])
        n = meta.get('rows_changed', 0)
        changed.append(n)
        print(f'[OK] 语句 {i} rows_changed={n}')
    return db, changed


def sync_codes(codes, exec_=False, rebuild=False, out=None):
    """对给定 code 列表跑 baolei，生成 SQL 并（可选）写 D1。

    供 CLI 与 add_stock.py 复用：单只收录时传 [code]，新增标的自动带上暴雷数据。
    返回 (写入行数, 跳过数, 评级分布 Counter)。
    """
    from collections import Counter
    results, zones = run_baolei(codes)
    stmts, n, skipped = build_sql(results, zones, rebuild=rebuild)
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write('\n'.join(stmts) + '\n')
        print(f'OK → {out}')
    print(f'  标的: {len(codes)} 只 ｜ 写入 risk_checks: {n} 只 ｜ 跳过(无年报数据): {skipped} 只')
    dist = Counter(results[c].get('rating') or '无数据' for c in results)
    print(f'  评级分布: ' + ' / '.join(f'{k} {v}' for k, v in dist.most_common()))
    miss = [c for c in codes if c in results and not zones.get(c)]
    if miss:
        print(f'  ⚠️ 五雷区说明缺失 {len(miss)} 只（报告文本未匹配，页面该列为空）')
    if exec_:
        exec_stmts(stmts)
        print('[D1] 完成')
    return n, skipped, dist


def main():
    ap = argparse.ArgumentParser(description='暴雷检查数据同步：stock-analytics baolei → D1 risk_checks')
    ap.add_argument('--exec', action='store_true', help='生成后直接写 D1')
    ap.add_argument('--codes', help='只处理这些 code（逗号分隔）。默认=线上 D1 全部 tracked=1')
    ap.add_argument('--all', action='store_true',
                    help='全量重建：先 DELETE FROM risk_checks 再插入（仅刷新全部评级时用）')
    ap.add_argument('--limit', type=int, default=0, help='仅前 N 只（调试用，不可与 --all 同用）')
    args = ap.parse_args()

    if args.all and args.limit:
        raise SystemExit('--all 与 --limit 不可同用（会清空整表却只写回 N 只）')
    if args.all and args.codes:
        raise SystemExit('--all 与 --codes 不可同用（全量重建不接受子集）')

    if args.codes:
        codes = sorted(c.strip() for c in args.codes.split(',') if c.strip())
        if not codes:
            raise SystemExit('--codes 为空')
        print(f'[codes] 指定标的：{len(codes)} 只')
    else:
        codes = site_codes()
    if args.limit:
        codes = codes[:args.limit]
        print(f'[codes] --limit 截取前 {len(codes)} 只（增量模式，不会影响其他标的）')

    # 指定子集时另存留档文件，避免覆盖全量种子 data/risk_seed.sql
    out = OUT if not args.codes else os.path.join(ROOT, 'data', 'risk_incremental.sql')
    sync_codes(codes, exec_=args.exec, rebuild=args.all, out=out)


if __name__ == '__main__':
    main()
