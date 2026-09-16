#!/usr/bin/env python3
"""stocks 站点 → 一键收录新票（stocks + industry_lines + tracking_rules + 验证 + 留档）

用法：
  # ① 检查研报标的在站内的收录情况（有无/分类），不写库
  python3 scripts/add_stock.py --check 600114.SH,300413.SZ

  # ② 收录（默认直接写 D1、验证、留档 data/seed_<code>.sql）
  python3 scripts/add_stock.py \
    --code 600114.SH --name 东睦股份 --sector 粉末冶金/MIM铰链 --category core \
    --tags "MIM铰链,折叠屏,软磁复合材料,AI算力电感" \
    --desc "四层筛子结论..." --pe 43.83 --pe-date 2026-08-31 \
    --buy-range "[30, 40]" \
    --line "mim-foldable:leader:primary:MIM铰链/折叠屏结构件:国内 MIM 第一梯队…" \
    --rule "MIM收入增速:MIM 平台主营业务收入同比:转负:0-10%:>20% 放量"

  # ③ 只生成 SQL 不写库
  python3 scripts/add_stock.py --dry-run --code ... --name ... --category ...

  # ④ 已存在时重收（先删旧 stocks/lines/rules 再插入）
  ... --replace

收录时会自动跑一次 baolei 并把暴雷检查增量写进 risk_checks（--no-risk 可跳过）。

tag 以英文逗号分隔；--line/--rule 可多次传入，字段以 : 分隔。
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_d1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # projects/stocks-site

CATEGORIES = ('core', 'frontier', 'swing', 'dividend', 'sunset')
BUY_RANGE_TYPES = ('pe', 'pe-fwd', 'pe-core', 'pb', 'ps', 'price')
LINE_CATS = ('mainline', 'frontier', 'explosion', 'swing', 'dividend', 'sunset')


def q(s: str) -> str:
    return str(s).replace("'", "''")


def parse_tags(s: str) -> str:
    if not s:
        return '[]'
    tags = [t.strip() for t in s.split(',') if t.strip()]
    return json.dumps(tags, ensure_ascii=False)


def parse_buy_range(s: str) -> str:
    if not s:
        return '[]'
    s = s.strip()
    if s.startswith('['):
        return s
    parts = [p.strip() for p in s.split(',')]
    return json.dumps([float(p) for p in parts])


def split_items(items, n, what):
    out = []
    for it in items or []:
        parts = it.split(':', n - 1)
        if len(parts) != n:
            raise SystemExit(f'--{what} 格式错误（期望 {n} 段，: 分隔）: {it}')
        out.append([p.strip() for p in parts])
    return out


def check_codes(codes):
    db = cf_d1.find_db()
    if not db:
        raise SystemExit('D1 不存在，先跑 create-bound')
    codes = [c.strip() for c in codes.split(',') if c.strip()]
    if not codes:
        raise SystemExit('--check 需要逗号分隔的 ts_code')
    # D1 HTTP API 不支持 ? 占位符，ts_code 为受控格式（数字+.SH/.SZ）直接内插
    in_list = ', '.join(f"'{c}'" for c in codes)
    ok, rows, _m, err = cf_d1.execute_sql(db, f"SELECT code, name, category, subtype FROM stocks WHERE code IN ({in_list})")
    if not ok:
        raise SystemExit('查询失败: ' + json.dumps(err, ensure_ascii=False))
    have = {r['code']: r for r in rows}
    print('== 站内收录情况 ==')
    for c in codes:
        r = have.get(c)
        print(f'  {c}  {"✅ " + r["name"] + " [" + r["category"] + "]" if r else "❌ 未收录"}')
    missing = [c for c in codes if c not in have]
    print(f'  合计 {len(codes)} 个，已收录 {len(have)}，未收录 {len(missing)}')
    return missing


def build_sql(a):
    lines_sql = None
    line_parts = split_items(a.line, 5, 'line')
    line_cats = list(getattr(a, 'line_cat', None) or [])
    if line_cats and len(line_cats) != len(line_parts or []):
        raise SystemExit(
            f'--line-cat 数量({len(line_cats)}) 与 --line 数量({len(line_parts or [])}) 不一致，'
            '请按 --line 顺序一一对应')
    if line_parts:
        if line_cats:
            vals = ', '.join(
                f"('{a.code}', '{q(p[0])}', '{q(p[1])}', '{q(p[2])}', '{q(line_cats[i])}', '{q(p[3])}', '{q(p[4])}', {i})"
                for i, p in enumerate(line_parts)
            )
            lines_sql = (
                "INSERT INTO industry_lines (stock_code, line_id, position, weight, lineCat, segment, note, sort_order) VALUES "
                + vals
            )
        else:
            vals = ', '.join(
                f"('{a.code}', '{q(p[0])}', '{q(p[1])}', '{q(p[2])}', '{q(p[3])}', '{q(p[4])}', {i})"
                for i, p in enumerate(line_parts)
            )
            lines_sql = (
                "INSERT INTO industry_lines (stock_code, line_id, position, weight, segment, note, sort_order) VALUES "
                + vals
            )

    rules_sql = None
    rule_parts = split_items(a.rule, 5, 'rule')
    if rule_parts:
        vals = ', '.join(
            f"('{a.code}', '{q(p[0])}', '{q(p[1])}', '{q(p[2])}', '{q(p[3])}', '{q(p[4])}', {i})"
            for i, p in enumerate(rule_parts)
        )
        rules_sql = (
            "INSERT INTO tracking_rules (stock_code, dimension, indicator, red, yellow, green, sort_order) VALUES "
            + vals
        )

    stocks_sql = (
        "INSERT INTO stocks (code, name, sector, category, subtype, tags, desc, pe_current, pe_date, ttm_buy_range, buy_range_type, tracked, added_at) VALUES "
        f"('{a.code}', '{q(a.name)}', '{q(a.sector)}', '{a.category}', '{q(a.subtype or '')}', "
        f"'{q(parse_tags(a.tags))}', '{q(a.desc or '')}', "
        f"{a.pe if a.pe is not None else 'NULL'}, '{a.pe_date or ''}', "
        f"'{parse_buy_range(a.buy_range)}', '{a.buy_range_type}', {1 if a.tracked else 0}, "
        f"'{a.added_at or ''}')"
    )
    parts = [stocks_sql]
    if lines_sql:
        parts.append(lines_sql)
    if rules_sql:
        parts.append(rules_sql)
    return parts, line_parts, rule_parts


def main():
    ap = argparse.ArgumentParser(description='stocks 站 D1 一键收录新票')
    ap.add_argument('--check', help='逗号分隔 ts_code，只检查站内收录情况')
    ap.add_argument('--code')
    ap.add_argument('--name')
    ap.add_argument('--sector', default='')
    ap.add_argument('--category', choices=CATEGORIES)
    ap.add_argument('--subtype', default='')
    ap.add_argument('--tags', default='')
    ap.add_argument('--desc', default='')
    ap.add_argument('--pe', type=float)
    ap.add_argument('--pe-date', default='')
    ap.add_argument('--buy-range', default='')
    ap.add_argument('--buy-range-type', default='pe', choices=BUY_RANGE_TYPES,
                    help='买点区间口径（默认 pe）；亏损/PE 失效用 pb 或 ps，绝对价用 price，前瞻用 pe-fwd，核心仓用 pe-core')
    ap.add_argument('--tracked', type=int, default=1)
    ap.add_argument('--added-at', default='')
    ap.add_argument('--line', action='append', help='line_id:position:weight:segment:note（可多次）')
    ap.add_argument('--line-cat', action='append', choices=LINE_CATS,
                    help='产业线分类 lineCat（mainline/frontier/explosion/swing/dividend/sunset），按 --line 顺序一一对应（可多次；不传则留空）')
    ap.add_argument('--rule', action='append', help='dimension:indicator:red:yellow:green（可多次）')
    ap.add_argument('--dry-run', action='store_true', help='只生成 SQL 不写库')
    ap.add_argument('--replace', action='store_true', help='已存在时先删旧记录再插入')
    ap.add_argument('--no-risk', action='store_true',
                    help='跳过收录时的暴雷检查写入（默认会自动跑 baolei 并增量写 risk_checks）')
    ap.add_argument('--out', help='留档 SQL 路径（默认 data/seed_<code>.sql）')
    a = ap.parse_args()

    if a.check:
        check_codes(a.check)
        return

    if not a.code or not a.name:
        raise SystemExit('--code 和 --name 必填（或用 --check 检查）')
    if a.category is None:
        raise SystemExit('--category 必填，可选: ' + ', '.join(CATEGORIES))

    # added_at 默认当前本地时间戳（'YYYY-MM-DD HH:MM:SS'），支持 --added-at 覆盖
    if not a.added_at:
        a.added_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db = cf_d1.find_db()
    if not db:
        raise SystemExit('D1 不存在，先跑 create-bound')

    # 已存在检查
    ok, existing, _m, err = cf_d1.execute_sql(
        db, f"SELECT code, name FROM stocks WHERE code = '{a.code}'")
    if not ok:
        raise SystemExit('查询失败: ' + json.dumps(err, ensure_ascii=False))
    if existing and not a.replace:
        print(f'⚠️  {a.code} 已在站内（{existing[0]["name"]}）。已存在时用 --replace 重收（会先删旧 stocks/lines/rules）。')
        return

    parts, line_parts, rule_parts = build_sql(a)
    sql_text = ';\n'.join(parts) + ';\n'
    out = a.out or os.path.join(ROOT, 'data', f'seed_{a.code.split(".")[0]}.sql')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(sql_text)

    if a.dry_run:
        print(f'[dry-run] SQL 已生成（未写库）: {out}')
        print(sql_text[:1000])
        return

    if a.replace:
        for stmt in [
            f"DELETE FROM industry_lines WHERE stock_code = '{a.code}'",
            f"DELETE FROM tracking_rules WHERE stock_code = '{a.code}'",
            f"DELETE FROM stocks WHERE code = '{a.code}'",
        ]:
            ok, _r, _m, err = cf_d1.execute_sql(db, stmt)
            if not ok:
                raise SystemExit('清理旧记录失败: ' + json.dumps(err, ensure_ascii=False))
        print(f'[replace] 已删除 {a.code} 旧 stocks/lines/rules')

    for i, stmt in enumerate(parts, 1):
        ok, rows, meta, err = cf_d1.execute_sql(db, stmt)
        if not ok:
            print(f'[FAIL] 语句 {i}: {stmt[:120]}...')
            print('  errors:', json.dumps(err, ensure_ascii=False)[:500])
            raise SystemExit(1)
        print(f'[OK] 语句 {i} last_row_id={meta.get("last_row_id", "")}')

    # 验证
    ok, rows, _m, err = cf_d1.execute_sql(
        db, f"SELECT code, name, category, pe_current, pe_date, ttm_buy_range, buy_range_type FROM stocks WHERE code = '{a.code}'")
    print('== 验证 ==')
    if ok and rows:
        r = rows[0]
        print(f'  stocks: {r["code"]} {r["name"]} [{r["category"]}] PE={r["pe_current"]} ({r["pe_date"]}) '
              f'买点={r["ttm_buy_range"]}@{r["buy_range_type"]}')
    if line_parts:
        ok, rows, _m, err = cf_d1.execute_sql(
            db, f"SELECT line_id, position, weight, lineCat FROM industry_lines WHERE stock_code = '{a.code}' ORDER BY sort_order")
        if ok:
            print('  lines:', ', '.join(
                f'{r["line_id"]}({r["position"]}/{r["weight"]}'
                f'{"/" + r["lineCat"] if r["lineCat"] else ""})' for r in rows))
    if rule_parts:
        ok, rows, _m, err = cf_d1.execute_sql(
            db, f"SELECT dimension FROM tracking_rules WHERE stock_code = '{a.code}' ORDER BY sort_order")
        if ok:
            print('  rules:', ', '.join(r['dimension'] for r in rows))
    print(f'SQL 留档: {out}')

    # 完整性检查：提示收录后还需补齐的数据（防"模板一样"问题再犯）
    print('== 完整性检查 ==')
    ok, rows, _m, _e = cf_d1.execute_sql(
        db, f"SELECT COUNT(*) AS n FROM pe_history WHERE stock_code = '{a.code}'")
    if ok and rows and rows[0]['n'] == 0:
        print(f'  ⚠️  pe_history 为空 → 运行: python3 scripts/backfill_pe.py --code {a.code}')
    else:
        print(f'  ✅ pe_history 已就绪')
    ok, rows, _m, _e = cf_d1.execute_sql(
        db, f"SELECT COUNT(*) AS n FROM tracking_data WHERE stock_code = '{a.code}'")
    if ok and rows and rows[0]['n'] == 0:
        print(f'  ⚠️  tracking_data（9维行情）为空 → 运行: python3 scripts/backfill_tracking.py --code {a.code}')
    else:
        print(f'  ✅ tracking_data 已就绪')
    if a.category in ('core', 'frontier'):
        ok, rows, _m, _e = cf_d1.execute_sql(
            db, f"SELECT COUNT(*) AS n FROM stock_modules WHERE stock_code = '{a.code}'")
        if ok and rows and rows[0]['n'] == 0:
            print(f'  ⚠️  {a.category} 类未写重点内容模块（stock_modules）→ 参照 data/seed_301165_modules.sql 补 position_check/zhongye_summary/fulfillment_track')
        else:
            print(f'  ✅ 重点内容模块已就绪')
    if a.category == 'swing':
        ok, rows, _m, _e = cf_d1.execute_sql(
            db, f"SELECT COUNT(*) AS n FROM stock_modules WHERE stock_code = '{a.code}' AND module_key = 'swing_discipline'")
        if ok and rows and rows[0]['n'] == 0:
            print(f'  ⚠️  swing 类未写波段纪律模块（swing_discipline）→ 参照 data/seed_swing_discipline.sql 补')
        else:
            print(f'  ✅ 波段纪律模块已就绪')
    if a.subtype == '爆发':
        ok, rows, _m, _e = cf_d1.execute_sql(
            db, f"SELECT COUNT(*) AS n FROM industry_lines WHERE stock_code = '{a.code}' AND lineCat = 'explosion'")
        if ok and rows and rows[0]['n'] == 0:
            print(f'  ⚠️  爆发型标的产线未标 lineCat=explosion → 重收时加 --line-cat explosion'
                  f'（或 UPDATE industry_lines SET lineCat=\'explosion\' WHERE stock_code=\'{a.code}\'）')
        else:
            print(f'  ✅ 爆发线已标 lineCat=explosion')
    if line_parts and not a.line_cat:
        ok, rows, _m, _e = cf_d1.execute_sql(
            db, f"SELECT COUNT(*) AS n FROM industry_lines WHERE stock_code = '{a.code}' AND lineCat != ''")
        if ok and rows and rows[0]['n'] == 0:
            print(f'  ⚠️  产线未标 lineCat → 重收时加 --line-cat（core 主脉常标 mainline，前瞻卡位标 frontier）')
        else:
            print(f'  ✅ 产线 lineCat 已标')

    # 暴雷检查：收录时同步写入 risk_checks（增量 UPSERT，不动其他标的）
    print('== 暴雷检查 ==')
    if a.no_risk:
        print('  ⏭  已跳过（--no-risk）')
    else:
        try:
            import sync_baolei
            n, _skipped, _dist = sync_baolei.sync_codes([a.code], exec_=True)
            if n:
                print(f'  ✅ risk_checks 已写入 {a.code}（增量，未影响其他标的）')
            else:
                print(f'  ⚠️  baolei 无该股年报数据（跳过）')
        except (Exception, SystemExit) as e:  # baolei 不可用/无数据不应让收录失败
            print(f'  ⚠️  暴雷数据写入失败（不影响本次收录）：{e}')
            print(f'     稍后补: python3 scripts/sync_baolei.py --codes {a.code} --exec')


if __name__ == '__main__':
    main()