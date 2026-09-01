#!/usr/bin/env python3
"""u4 迁移数据全量入库 D1（并发批量版）
   幂等：先删该股 5 类旧数据（含 blocks 孤块），再插新。
   D1 支持 INSERT...RETURNING id + 多行 VALUES → 并发 8 worker。
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cf_d1 import call, find_db, ACCOUNT_ID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ('positioning_check', 'upgrade_downgrade', 'valuation', 'risk',
        'tracking_table', 'falsify_line')

def main():
    db = find_db(); uid = db['uuid']
    def run(sql):
        d = call('POST', f'/accounts/{ACCOUNT_ID}/d1/database/{uid}/query', {'sql': sql})
        if not d.get('success'):
            raise RuntimeError(f"{sql[:90]} -> {d.get('errors')}")
        return d['result'][0]
    def q(s): return str(s).replace("'", "''")

    mig = json.load(open(os.path.join(ROOT, 'data', 'u4_migrate.json')))
    wl = {r['code'].split('.')[0]: r['code'] for r in json.load(open(os.path.join(ROOT, 'data', 'u4_watchlist.json')))}
    items = [(wl[c], d) for c, d in mig.items() if c in wl]

    # ---------- 阶段1：清理（顺序执行，避免并发同表删除） ----------
    dels = ', '.join(f"'{k}'" for k in KEYS)
    for code, _ in items:
        run(f"DELETE FROM module_blocks WHERE module_id IN "
            f"(SELECT id FROM stock_modules WHERE stock_code='{code}' AND module_key IN ({dels}))")
        run(f"DELETE FROM stock_modules WHERE stock_code='{code}' AND module_key IN ({dels})")
        run(f"DELETE FROM catalysts WHERE stock_code='{code}'")
    print(f'[阶段1] 清理 {len(items)} 只完成')

    # ---------- 阶段2/3：并发插入 ----------
    def work(code, d):
        # 催化剂：一条多行 INSERT
        cats = d.get('catalysts') or []
        if cats:
            vals = ', '.join(
                f"('{code}', '{q(c['name'])}', '{q(c['due'])}', 'pending', '{q(c['note'])}', {i})"
                for i, c in enumerate(cats))
            run(f"INSERT INTO catalysts (stock_code, name, due_date, status, note, sort_order) VALUES {vals}")
        # 模块：INSERT...RETURNING id → blocks 批量
        for mod in d['modules']:
            r = run(f"INSERT INTO stock_modules (stock_code, module_key, title, template_key, sort_order, visible) "
                    f"VALUES ('{code}', '{mod['key']}', '{q(mod['title'])}', '{mod['key']}', 2, 1) RETURNING id")
            mid = r['results'][0]['id']
            if mod['blocks']:
                vals = []
                for so, b in enumerate(mod['blocks']):
                    if b['type'] == 'table':
                        payload = {'headers': b['headers'], 'rows': b['rows']}
                    elif b['type'] == 'callout':
                        payload = {'text': b.get('text', ''), 'tone': b.get('tone', '')}
                    else:
                        payload = {'text': b.get('text', '')}
                    vals.append(f"({mid}, '{b['type']}', '{q(json.dumps(payload, ensure_ascii=False))}', {so})")
                run(f"INSERT INTO module_blocks (module_id, block_type, data_json, sort_order) VALUES "
                    + ', '.join(vals))
        return (code, len(cats), len(d['modules']))

    n_cat = n_mod = 0
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(work, code, d): (code, d) for code, d in items}
        for f in as_completed(futs):
            code, nc, nm = f.result()
            n_cat += nc; n_mod += nm
            done += 1
            if done % 30 == 0:
                print(f'  ...{done}/{len(items)} 股票')
    print(f'入库完成: {done} 只股票, 模块 {n_mod}, 催化 {n_cat}')

if __name__ == '__main__':
    main()