#!/usr/bin/env python3
"""构建 dist 部署目录：worker_src → dist/_worker.js"""
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'worker_src', '_worker.js')
DST = os.path.join(ROOT, 'dist', '_worker.js')

shutil.copyfile(SRC, DST)
print(f'_worker.js 已同步 → {DST}')