#!/usr/bin/env python3
"""构建 dist 部署目录：worker_src → dist/_worker.js；assets → dist/assets/"""
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'worker_src', '_worker.js')
DST = os.path.join(ROOT, 'dist', '_worker.js')

shutil.copyfile(SRC, DST)
print(f'_worker.js 已同步 → {DST}')

# 静态资源（favicon 等）同步到 dist/assets/
SRC_ASSETS = os.path.join(ROOT, 'assets')
DST_ASSETS = os.path.join(ROOT, 'dist', 'assets')
os.makedirs(DST_ASSETS, exist_ok=True)
for name in os.listdir(SRC_ASSETS):
    src = os.path.join(SRC_ASSETS, name)
    if os.path.isfile(src):
        shutil.copyfile(src, os.path.join(DST_ASSETS, name))
        print(f'assets/{name} 已同步 → dist/assets/{name}')