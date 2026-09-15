#!/usr/bin/env python3
"""构建 dist 部署目录（dist/ 是纯产物，不入版本控制；真源在 web/ 与 worker_src/）：

1. worker_src/_worker.js → dist/_worker.js
2. web/assets/* → dist/assets/（前端成品 js/css + favicon）
3. web/*.html → 注入 /assets/ 资源**内容指纹** → dist/*.html

关于第 3 步：web/assets/*.js|css 是直接手写的成品文件（不经打包器），
HTML 里是裸路径引用；改了内容但 URL 不变时，浏览器/CDN 会继续喂旧文件
（2026-09-15 部署 `.badge.light-gray` 时实测踩到：首次 curl 拿到 21713B 旧缓存）。
用文件内容哈希做版本号 —— 内容不变则 URL 不变（不会无谓失效），
内容一变 URL 必变（强制回源），且重复构建幂等。

关于源/产物分离（2026-09-15 改造）：
改造前 dist/*.html 既是手写的源、又被本脚本就地注入指纹改写，
而 dist/ 被 .gitignore 排除 —— 等于整个前端没有版本控制、没有备份。
现在源在 web/（存**不带指纹**的干净 HTML），dist/ 只承载产物，可随时删掉重建。
"""
import hashlib
import os
import re
import shutil
import glob

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, 'web')
SRC_ASSETS = os.path.join(WEB, 'assets')
DIST = os.path.join(ROOT, 'dist')
DST_ASSETS = os.path.join(DIST, 'assets')

# ---------------- 1) worker ----------------
SRC = os.path.join(ROOT, 'worker_src', '_worker.js')
DST = os.path.join(DIST, '_worker.js')
os.makedirs(DIST, exist_ok=True)
shutil.copyfile(SRC, DST)
print(f'_worker.js 已同步 → {DST}')

# ---------------- 2) assets ----------------
os.makedirs(DST_ASSETS, exist_ok=True)
for name in sorted(os.listdir(SRC_ASSETS)):
    src = os.path.join(SRC_ASSETS, name)
    if os.path.isfile(src):
        shutil.copyfile(src, os.path.join(DST_ASSETS, name))
        print(f'web/assets/{name} 已同步 → dist/assets/{name}')

# ---------------- 3) HTML：注入指纹并输出 ----------------
# 匹配 /assets/<文件>，可带已有的 ?v=xxx（重复构建时先剥掉再加，保证幂等）
ASSET_REF = re.compile(r'(?P<path>/assets/[A-Za-z0-9_.\-]+?)(?:\?v=[0-9a-z]+)?(?=["\'\s>])')


def fingerprint(url_path: str):
    """返回 /assets/xxx 对应文件的内容指纹（前 8 位 md5）；文件不存在返回 None。"""
    fp = os.path.join(DST_ASSETS, os.path.basename(url_path))
    if not os.path.isfile(fp):
        return None
    with open(fp, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()[:8]


def stamp(html: str):
    """给 HTML 里所有 /assets/ 引用补/更新 ?v=指纹。返回 (新文本, 命中数, 缺失文件列表)。"""
    hits, missing = [], []

    def repl(m):
        path = m.group('path')
        ver = fingerprint(path)
        if ver is None:
            missing.append(path)
            return path
        hits.append(path)
        return f'{path}?v={ver}'

    return ASSET_REF.sub(repl, html), hits, missing


stamped_files = 0
for src_path in sorted(glob.glob(os.path.join(WEB, '*.html'))):
    name = os.path.basename(src_path)
    raw = open(src_path, encoding='utf-8').read()
    out, hits, missing = stamp(raw)
    out_path = os.path.join(DIST, name)
    prev = open(out_path, encoding='utf-8').read() if os.path.isfile(out_path) else None
    open(out_path, 'w', encoding='utf-8').write(out)
    if prev != out:
        stamped_files += 1
    if missing:
        print(f'  ⚠️ {name}: 资源文件缺失 {sorted(set(missing))}（未加指纹）')
    print(f'  {name}: 指纹 {len(hits)} 处'
          + ('（已更新）' if prev != out else '（无需变更）'))

print(f'HTML 资源指纹完成：{stamped_files} 个文件有变更')
