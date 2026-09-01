#!/usr/bin/env python3
"""批量抓取 u4 详情页正文（145 只），存 JSON：data/u4_pages_raw.json
u4 假登录（visitor name），正文在 SSR HTML 中可直接 innerText 提取。
v3：修复异步加载未完成问题 —— 每页滚动到底触发懒加载 + 轮询等"加载"占位消失且长度稳定 + 质量门重试。
环境变量：
  SPEC_CODES=300049,002056  只抓指定代码（验证用，逗号分隔）
  RETRY_ONLY=1              只重抓 data/retry_codes.json 里的代码
"""
import asyncio, json, os, sys

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'https://u4-stocks.xiaoxia.io'
# 质量判定：已知 section 命中数（innerText 空白压缩后长度不可靠，用内容特征）
SECTIONS = ('拐点核验', '兑现跟踪', '证伪线', '估值分析', '风险提示', '催化节点时间表',
            '四层筛子评估', '定位核验', '升级 / 降级信号', '关键财务', '产业主脉')
MIN_HITS = 2
LOADING_HINTS = ('加载催化', '加载风险', '加载信号', '加载中', '正在加载')

async def main():
    rows = json.load(open(os.path.join(ROOT, 'data', 'u4_watchlist.json')))
    out_path = os.path.join(ROOT, 'data', 'u4_pages_raw.json')
    out = {}
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        try:
            out = json.load(open(out_path))
        except Exception:
            out = {}
    codes_all = [r['code'].split('.')[0] for r in rows]

    spec = [c.strip() for c in os.environ.get('SPEC_CODES', '').split(',') if c.strip()]
    retry_only = os.environ.get('RETRY_ONLY', '0') == '1'
    force_all = os.environ.get('FORCE_ALL', '0') == '1'
    if spec:
        todo = spec
    elif force_all:
        todo = codes_all
        out = {}   # 全量覆盖
    elif retry_only:
        retry = json.load(open(os.path.join(ROOT, 'data', 'retry_codes.json')))
        todo = list(retry)
        for c in todo:
            out.pop(c, None)   # 强制覆盖重抓
    else:
        todo = [c for c in codes_all if c not in out]

    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        # 登录（假登录：填 visitor name）
        await pg.goto(f'{BASE}/login', wait_until='domcontentloaded')
        try:
            await pg.fill('#visitorname', 'txohyeah')
            await pg.click('button:has-text("进入")')
            await pg.wait_for_timeout(1800)
        except Exception as e:
            print('登录标记:', e)
        # 探测已登录
        await pg.goto(f'{BASE}/', wait_until='domcontentloaded')
        await pg.wait_for_timeout(800)
        if '/login' in pg.url:
            print('!! 仍在登录页，中止'); return
        print(f'登录成功，待抓 {len(todo)} 只')

        errs, warn = [], []
        t0 = asyncio.get_event_loop().time()
        for i, code in enumerate(todo, 1):
            body = ''
            ok = False
            for attempt in range(2):
                try:
                    await pg.goto(f'{BASE}/pages/{code}.html', wait_until='domcontentloaded')
                    # 滚动到底 3 轮，触发懒加载
                    for _ in range(3):
                        await pg.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                        await pg.wait_for_timeout(450)
                    # 初始等待 4s：避开异步渲染起步期的"假稳定"（早期 SSR 与完整版长度可能相同）
                    await pg.wait_for_timeout(4000)
                    # 轮询：无加载占位 且 长度稳定 → 认为渲染完成（上限 13s）
                    prev_len = -1
                    for _ in range(26):
                        await pg.wait_for_timeout(500)
                        body = await pg.evaluate('document.body.innerText')
                        L = len(body)
                        stable = (L >= 500 and L == prev_len)
                        no_loading = not any(h in body for h in LOADING_HINTS)
                        if stable and no_loading:
                            break
                        prev_len = L
                    # 质量门：section 命中数（防错误页/未渲染）
                    hits = sum(1 for k in SECTIONS if k in body)
                    if hits >= MIN_HITS and not any(h in body for h in LOADING_HINTS):
                        ok = True
                        break
                    warn.append((code, attempt, len(body), hits))
                    await pg.wait_for_timeout(1500)
                except Exception as e:
                    errs.append((code, str(e)))
                    body = f'ERROR {e}'
                    break
            out[code] = {'title': await pg.title(), 'url': pg.url, 'text': body}
            if i % 10 == 0:
                json.dump(out, open(out_path, 'w'), ensure_ascii=False)
                el = asyncio.get_event_loop().time() - t0
                print(f'  ...{i}/{len(todo)} len={len(body)} elapsed={el:.0f}s')
        json.dump(out, open(out_path, 'w'), ensure_ascii=False)
        await b.close()
    print(f'完成: {len(out)} 只, 错误 {len(errs)}')
    if warn:
        print('质量警告(两次失败仍不达标):', len(warn))
        for c, a, L, h in warn[:15]:
            print(f'  {c} attempt{a} len={L} hits={h}')
    if errs:
        print('错误清单:', errs[:10])
    bad = [c for c, d in out.items() if '/login' in str(d.get('url'))]
    print('被重定向到登录的:', bad[:10], f'({len(bad)})')

if __name__ == '__main__':
    asyncio.run(main())