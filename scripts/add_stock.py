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

tag 以英文逗号分隔；--line/--rule 可多次传入，字段以 : 分隔。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_d1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # projects/stocks-site

CATEGORIES = ('core', 'frontier', 'swing', 'dividend', 'sunset')


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
    if line_parts:
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
        f"'{parse_buy_range(a.buy_range)}', 'pe', {1 if a.tracked else 0}, "
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
    ap.add_argument('--tracked', type=int, default=1)
    ap.add_argument('--added-at', default='')
    ap.add_argument('--line', action='append', help='line_id:position:weight:segment:note（可多次）')
    ap.add_argument('--rule', action='append', help='dimension:indicator:red:yellow:green（可多次）')
    ap.add_argument('--dry-run', action='store_true', help='只生成 SQL 不写库')
    ap.add_argument('--replace', action='store_true', help='已存在时先删旧记录再插入')
    ap.add_argument('--out', help='留档 SQL 路径（默认 data/seed_<code>.sql）')
    a = ap.parse_args()

    if a.check:
        check_codes(a.check)
        return

    if not a.code or not a.name:
        raise SystemExit('--code 和 --name 必填（或用 --check 检查）')
    if a.category is None:
        raise SystemExit('--category 必填，可选: ' + ', '.join(CATEGORIES))

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
        db, f"SELECT code, name, category, pe_current, pe_date FROM stocks WHERE code = '{a.code}'")
    print('== 验证 ==')
    if ok and rows:
        r = rows[0]
        print(f'  stocks: {r["code"]} {r["name"]} [{r["category"]}] PE={r["pe_current"]} ({r["pe_date"]})')
    if line_parts:
        ok, rows, _m, err = cf_d1.execute_sql(
            db, f"SELECT line_id, position, weight FROM industry_lines WHERE stock_code = '{a.code}' ORDER BY sort_order")
        if ok:
            print('  lines:', ', '.join(f'{r["line_id"]}({r["position"]}/{r["weight"]})' for r in rows))
    if rule_parts:
        ok, rows, _m, err = cf_d1.execute_sql(
            db, f"SELECT dimension FROM tracking_rules WHERE stock_code = '{a.code}' ORDER BY sort_order")
        if ok:
            print('  rules:', ', '.join(r['dimension'] for r in rows))
    print(f'SQL 留档: {out}')


if __name__ == '__main__':
    main()