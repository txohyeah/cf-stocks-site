#!/usr/bin/env python3
"""stocks 站点种子数据生成器
从 u4 归档 JSON（api_stocks.json / api_industries.json）生成 D1 seed SQL。
用法： python3 scripts/seed_builder.py [--admin-pass PASS]
口令未指定时自动生成 16 位随机口令并打印（仅此一次，交给站点主人）。
"""
import argparse
import ast
import base64
import hashlib
import json
import os
import secrets as pysecrets
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(ROOT))
ARCHIVE = os.path.join(WORKSPACE, 'media', 'u4_site_archive')
OUT = os.path.join(ROOT, 'data', 'seed.sql')

PBKDF2_ITER = 100000
PBKDF2_KEYLEN = 32


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def sql_escape(s):
    return str(s).replace("'", "''")


def to_json_str(v):
    """把 JSON 对象或 Python 字面量字符串规范成 JSON 字符串。"""
    if isinstance(v, str):
        try:
            v = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            pass
    return json.dumps(v, ensure_ascii=False)


def hash_pass(passphrase: str) -> str:
    salt = pysecrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', passphrase.encode('utf-8'), salt, PBKDF2_ITER, dklen=PBKDF2_KEYLEN)
    return f"pbkdf2${PBKDF2_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def build_users(admin_pass: str) -> str:
    ts = now_iso()
    h = hash_pass(admin_pass)
    return (f"INSERT OR REPLACE INTO users (username, passphrase_hash, role, active, created_at, updated_at) "
            f"VALUES ('admin', '{h}', 'admin', 1, '{ts}', '{ts}');\n")


def build_stocks() -> str:
    path = os.path.join(ARCHIVE, 'api_stocks.json')
    with open(path) as f:
        items = json.load(f)
    rows = []
    for s in items:
        pc = s.get('peCurrent')
        pc_sql = 'NULL'
        if pc not in (None, ''):
            try:
                pc_sql = float(pc)
            except (ValueError, TypeError):
                pc_sql = 'NULL'
        rows.append(
            f"('{sql_escape(s['code'])}', '{sql_escape(s['name'])}', '{sql_escape(s.get('sector', ''))}', "
            f"'{sql_escape(s.get('industryCat', ''))}', '', "
            f"'{sql_escape(to_json_str(s.get('tags', [])))}', '{sql_escape(s.get('desc', ''))}', "
            f"{pc_sql}, "
            f"'{sql_escape(s.get('peDate', ''))}', "
            f"'{sql_escape(to_json_str(s.get('ttmBuyRange', [])))}', "
            f"'{sql_escape(s.get('buyRangeType', 'pe'))}', "
            f"{1 if s.get('tracked', True) else 0}, '{sql_escape(s.get('addedAt', ''))}')")
    stmt = "INSERT OR REPLACE INTO stocks (code, name, sector, category, subtype, tags, desc, pe_current, pe_date, ttm_buy_range, buy_range_type, tracked, added_at) VALUES\n" + ",\n".join(rows) + ";\n"
    return stmt


def build_industries() -> str:
    path = os.path.join(ARCHIVE, 'api_industries.json')
    with open(path) as f:
        items = json.load(f)
    rows = []
    for x in items:
        rows.append(
            f"('{sql_escape(x['id'])}', '{sql_escape(x['name'])}', '{sql_escape(x['stage'])}', "
            f"'{sql_escape(x.get('summary', ''))}', "
            f"'{sql_escape(to_json_str(x.get('segments', [])))}', "
            f"'{sql_escape(to_json_str(x.get('tags', [])))}', "
            f"'{sql_escape(to_json_str(x.get('trackIndicators', [])))}')")
    stmt = "INSERT OR REPLACE INTO industries (id, name, stage, summary, segments, tags, track_indicators) VALUES\n" + ",\n".join(rows) + ";\n"
    return stmt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--admin-pass', default=None)
    args = ap.parse_args()

    admin_pass = args.admin_pass or pysecrets.token_urlsafe(12)[:16]

    parts = ['-- stocks 站点 seed（由 seed_builder.py 生成）--\n']
    parts.append(build_users(admin_pass))
    parts.append(build_stocks())
    parts.append(build_industries())

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write('\n'.join(parts))

    n_stock = 0
    with open(os.path.join(ARCHIVE, 'api_stocks.json')) as f:
        n_stock = len(json.load(f))
    n_ind = 0
    with open(os.path.join(ARCHIVE, 'api_industries.json')) as f:
        n_ind = len(json.load(f))

    print(f'OK  seed.sql 已生成 → {OUT}')
    print(f'    stocks: {n_stock} | industries: {n_ind}')
    print(f'    admin 口令: {admin_pass}')


if __name__ == '__main__':
    main()