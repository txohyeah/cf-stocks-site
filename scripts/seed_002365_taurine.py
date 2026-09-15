#!/usr/bin/env python3
"""永安药业 002365.SZ swing 收录：新建 taurine 产业线 + stocks + lines + rules + 波段纪律模块"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_d1

db = cf_d1.find_db()
if not db:
    raise SystemExit('D1 不存在')

def run(stmt, label):
    ok, rows, meta, err = cf_d1.execute_sql(db, stmt)
    if not ok:
        print(f'[FAIL] {label}:', json.dumps(err, ensure_ascii=False)[:300])
        raise SystemExit(1)
    print(f'[OK] {label} last_row_id={meta.get("last_row_id","")}')
    return rows

# 1. 新建产业线（幂等：先删再插）
run("DELETE FROM industries WHERE id='taurine'", 'del industries')
run(
    "INSERT INTO industries (id, name, stage, summary, segments, tags, track_indicators) VALUES ("
    "'taurine', '牛磺酸/食品添加剂', 'mature', "
    "'全球牛磺酸产量 90%+ 在中国，五家厂商（永安/新和成/湖北远大/江阴华昌/江苏远洋）垄断；需求端能量饮料/宠物食品/饲料限抗温和增长，价格由供需周期决定，2026 年中东冲突引发抢购潮量价齐升，但圣元环保 4 万吨新产能 2027 年投放构成供给压力。', "
    "'[\"牛磺酸\", \"保健食品\", \"肌酸\"]', "
    "'[\"牛磺酸\", \"食品添加剂\", \"能量饮料\", \"周期反转\"]', "
    "'[{\"indicator\": \"牛磺酸价格\", \"green\": \">2.5 万/吨且量价齐升\", \"yellow\": \"2-2.5 万/吨持稳\", \"red\": \"回落至 2 万/吨以下\"}, {\"indicator\": \"新增产能投放\", \"green\": \"无新产能投产\", \"yellow\": \"圣元环保设备调试/试产\", \"red\": \"圣元环保 4 万吨投产且价格承压\"}, {\"indicator\": \"下游需求\", \"green\": \"能量饮料/宠物食品需求放量\", \"yellow\": \"需求平稳\", \"red\": \"客户去库存、订单下滑\"}]'"
    ")",
    'insert industries taurine'
)

# 2. stocks 主记录（swing）
run(
    "INSERT INTO stocks (code, name, sector, category, subtype, tags, desc, pe_current, pe_date, ttm_buy_range, buy_range_type, tracked, added_at) VALUES ("
    "'002365.SZ', '永安药业', '牛磺酸/食品添加剂', 'swing', '', "
    "'[\"牛磺酸\", \"食品添加剂\", \"能量饮料\", \"周期反转\", \"全球龙头\"]', "
    "'技术短线（周期兑现型）：全球牛磺酸龙头（50%+ 份额、7.8 万吨产能），2026H1 周期反转确认（营收+53%、扣非+1622%，中东冲突引发抢购量价齐升）。四层筛子 2.5/4：①格局壁垒过（寡头）②价值量⚠️（添加剂占下游成本极低，无技术升级通胀逻辑）③供需⚠️（短期改善、圣元环保 4 万吨新产能 2027 冲击）④弹性过但壁垒延续存疑。周期股非成长股，波段操作，跟踪牛磺酸价格+圣元环保投产+2026 年报扣非验证。', "
    "75.15, '2026-09-11', '[9.5, 11.5]', 'price', 1, '2026-09-14 00:00:00'"
    ")",
    'insert stocks'
)

# 3. 产业线
run(
    "INSERT INTO industry_lines (stock_code, line_id, position, weight, segment, note, sort_order) VALUES ("
    "'002365.SZ', 'taurine', 'leader', 'primary', '牛磺酸', '全球龙头 50%+ 份额、7.8 万吨/年产能，红牛/雀巢/可口可乐供应商；2026H1 牛磺酸营收 3.99 亿（+69%，占 71%）', 0"
    ")",
    'insert industry_lines'
)

# 4. 红绿灯规则（swing 页面不渲染，但留数据供后续升级 core 用）
run(
    "INSERT INTO tracking_rules (stock_code, dimension, indicator, red, yellow, green, sort_order) VALUES "
    "('002365.SZ', '牛磺酸价格', '牛磺酸市场均价', '回落至 2 万/吨以下', '2-2.5 万/吨持稳', '>2.5 万/吨且量价齐升', 0), "
    "('002365.SZ', '新增产能', '圣元环保 4 万吨项目', '投产且价格承压', '设备调试/试产', '未投产', 1), "
    "('002365.SZ', '利润含金量', '2026 年报扣非同比', '转负', '0-50%', '>50% 增长', 2)",
    'insert tracking_rules'
)

# 5. 波段纪律模块（swing 专属）
run(
    "INSERT INTO stock_modules (id, stock_code, module_key, title, template_key, sort_order, visible) VALUES "
    "(2001, '002365.SZ', 'swing_discipline', '⚡ 波段纪律', '', 1, 1)",
    'insert stock_modules'
)
run(
    "INSERT INTO module_blocks (id, module_id, block_type, data_json, sort_order) VALUES "
    "(8001, 2001, 'callout', '{\"text\":\"**分类：技术短线（周期兑现型）**\\n\\n全球牛磺酸龙头（50%+ 份额、7.8 万吨产能），2026H1 周期反转确认：营收+53.4%、归母+247%、扣非+1622%（中东冲突引发抢购、量价齐升）。但四层筛子 2.5/4——②价值量⚠️（添加剂占下游成本极低、无技术升级通胀逻辑）③供需⚠️（圣元环保 4 万吨新产能 2027 年投放）④壁垒延续存疑。周期股的钱不是成长股的钱，只做波段。\",\"tone\":\"info\"}', 1), "
    "(8002, 2001, 'table', '{\"headers\":[\"信号\",\"条件\"],\"rows\":[[\"进场\",\"回调至 9.5-11.5 元区间（2027E 20-24x）分批，牛磺酸价格维持 2.5 万/吨以上\"],[\"止损\",\"跌破 9 元（PB<1.35），或牛磺酸价格回落至 2 万/吨以下\"],[\"止盈\",\"反弹至 15-17 元（2026 年区间上沿）减仓，或 PE 冲高回落\"],[\"仓位上限\",\"≤5%（周期波段仓）\"]]}', 2), "
    "(8003, 2001, 'callout', '{\"text\":\"**风险**：圣元环保 4 万吨新产能 2027 年投产冲击供给；牛磺酸价格回落（中东冲突溢价消退）；实控人陈勇 2025 年被留置、二代接班治理不确定；环氧乙烷装置停产原料全外购；坏账计提比例上调+经营现金流-37%；baolei 评级高（2025 扣非为负，利润含金量待年度验证）。\",\"tone\":\"warn\"}', 3)",
    'insert module_blocks'
)

# 6. 验证
print('== 验证 ==')
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT code, name, category, pe_current, ttm_buy_range, buy_range_type FROM stocks WHERE code='002365.SZ'")
print('stocks:', rows if ok else err)
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT line_id, position, weight, segment FROM industry_lines WHERE stock_code='002365.SZ'")
print('lines:', rows if ok else err)
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT COUNT(*) AS n FROM module_blocks WHERE module_id=2001")
print('blocks:', rows if ok else err)
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT id, name, stage FROM industries WHERE id='taurine'")
print('industries:', rows if ok else err)