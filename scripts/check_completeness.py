#!/usr/bin/env python3
"""全站数据完整性扫描：找出详情页会"缺内容"的股票。

检查项：
  1. pe_history 为空（估值图缺失）
  2. core/frontier 类无重点内容模块（stock_modules）
  3. swing 类无波段纪律模块（swing_discipline）
  4. subtype=爆发 但产线未标 lineCat=explosion
  5. 无产业线（industry_lines 为空）
  6. 无暴雷检查数据（risk_checks 缺行 → 详情页 🛡️ 模块空白）

用法：
  python3 scripts/check_completeness.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import find_db, execute_sql


def main():
    db = find_db()
    if not db:
        raise SystemExit('D1 不存在')

    checks = [
        ('pe_history 为空（估值图缺失）',
         "SELECT s.code, s.name, s.category FROM stocks s WHERE s.tracked=1 "
         "AND NOT EXISTS (SELECT 1 FROM pe_history p WHERE p.stock_code=s.code)"),
        ('core/frontier 无重点内容模块',
         "SELECT s.code, s.name, s.category FROM stocks s WHERE s.tracked=1 AND s.category IN ('core','frontier') "
         "AND NOT EXISTS (SELECT 1 FROM stock_modules m WHERE m.stock_code=s.code)"),
        ('swing 无波段纪律模块',
         "SELECT s.code, s.name, s.category FROM stocks s WHERE s.tracked=1 AND s.category='swing' "
         "AND NOT EXISTS (SELECT 1 FROM stock_modules m WHERE m.stock_code=s.code AND m.module_key='swing_discipline')"),
        ('subtype=爆发 但产线未标 explosion',
         "SELECT s.code, s.name, s.category FROM stocks s WHERE s.tracked=1 AND s.subtype='爆发' "
         "AND NOT EXISTS (SELECT 1 FROM industry_lines l WHERE l.stock_code=s.code AND l.lineCat='explosion')"),
        ('无产业线',
         "SELECT s.code, s.name, s.category FROM stocks s WHERE s.tracked=1 "
         "AND NOT EXISTS (SELECT 1 FROM industry_lines l WHERE l.stock_code=s.code)"),
        ('无暴雷检查数据（详情页 🛡️ 模块空白）',
         "SELECT s.code, s.name, s.category FROM stocks s WHERE s.tracked=1 "
         "AND NOT EXISTS (SELECT 1 FROM risk_checks r WHERE r.stock_code=s.code)"),
    ]

    total_issues = 0
    for label, sql in checks:
        ok, rows, _m, _e = execute_sql(db, sql)
        if not ok:
            print(f'[FAIL] {label}: {_e}')
            continue
        if rows:
            total_issues += len(rows)
            print(f'⚠️  {label}（{len(rows)} 只）:')
            for r in rows:
                print(f'    {r["code"]} {r["name"]} [{r["category"]}]')
        else:
            print(f'✅ {label}: 无')
    print(f'\n共 {total_issues} 个问题' if total_issues else '\n全部通过 ✅')


if __name__ == '__main__':
    main()