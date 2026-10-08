#!/usr/bin/env python3
"""圣泉集团 605589.SH swing 收录：新建 electronic-resin 产业线 + stocks + lines + rules + 波段纪律模块（2026-09-22）"""
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
run("DELETE FROM industries WHERE id='electronic-resin'", 'del industries')
run(
    "INSERT INTO industries (id, name, stage, summary, segments, tags, track_indicators) VALUES ("
    "'electronic-resin', '电子树脂/覆铜板材料', 'grow', "
    "'AI 服务器高速覆铜板带动高频高速树脂（PPO/OPE/碳氢）需求爆发，2025 年全球电子级高端树脂市场 50-60 亿元，2027E 约 117 亿（CAGR 近 50%）；全球高端由 SABIC/三菱瓦斯主导，圣泉是国内唯一千吨级量产电子级 PPO（国内份额约 70%，M6-M9 全系列、M10 认证中），东材科技碳氢树脂领先；CCL→PCB→终端三重认证周期 1-2 年构成壁垒；2026-2029 国内新产能（东材 2 万吨、同宇、银禧）集中释放是中期供给压力。', "
    "'[\"PPO/OPE 树脂\", \"碳氢树脂\", \"电子级酚醛/环氧\", \"多孔碳/硅碳负极\"]', "
    "'[\"电子树脂\", \"PPO\", \"覆铜板上游\", \"AI服务器\", \"国产替代\"]', "
    "'[{\"indicator\": \"PPO 供需\", \"green\": \"满产满销且报价坚挺\", \"yellow\": \"报价持稳但新产能试产\", \"red\": \"高端报价回落 30%+ 或库存堆积\"}, {\"indicator\": \"竞争产能\", \"green\": \"东材/同宇/银禧未实质放量\", \"yellow\": \"新产能投产爬坡\", \"red\": \"东材 2 万吨满产冲击高端市场\"}, {\"indicator\": \"下游需求\", \"green\": \"AI 服务器 PCB 需求放量、M8/M9 渗透提升\", \"yellow\": \"需求平稳\", \"red\": \"AI 资本开支退坡、CCL 去库存\"}]'"
    ")",
    'insert industries electronic-resin'
)

# 2. stocks 主记录（swing）
run(
    "INSERT INTO stocks (code, name, sector, category, subtype, tags, desc, pe_current, pe_date, ttm_buy_range, buy_range_type, tracked, added_at) VALUES ("
    "'605589.SH', '圣泉集团', '合成树脂/电子材料', 'swing', '', "
    "'[\"酚醛树脂\", \"PPO电子树脂\", \"覆铜板上游\", \"多孔碳\", \"周期+成长\"]', "
    "'技术短线（成长兑现型）：全球酚醛/呋喃树脂龙头（65 万吨/12 万吨产能、产销国内第一），国内唯一千吨级电子级 PPO 供应商（M6-M9 全系列、过英伟达/华为/台光/生益认证），多孔碳市占率前二。四层筛子 3/4：①格局壁垒过 ②价值量过（M 级升级=单价台阶）③供需短期过、2026-2029 国内新产能集中释放中期压力 ④弹性未兑现（2026H1 归母 -10.7%，剔除股份支付 +4.3%）。经营现金流连年为负（2026H1 -9.75 亿）扩张失血，资产负债率 +8.7pct。波段操作，跟踪现金流/PPO 新线/竞争产能。', "
    "36.0, '2026-09-22', '[32, 36]', 'price', 1, '2026-09-22 00:00:00'"
    ")",
    'insert stocks'
)

# 3. 产业线
run(
    "INSERT INTO industry_lines (stock_code, line_id, position, weight, segment, note, sort_order) VALUES ("
    "'605589.SH', 'electronic-resin', 'leader', 'primary', '高频高速电子树脂', '酚醛 65 万吨/呋喃 12 万吨全球龙头（2026 酚醛涨价周期）；电子级 PPO/OPE 国内唯一千吨级量产（1500 吨满产+2000 吨新线 2026/9 投产），国内份额约 70%；多孔碳 2000 吨在产+1.5 万吨在建、25 亿加码硅碳负极一体化为第二曲线；2026H1 电子材料及电池材料营收 10.39 亿（+22.9%）', 0"
    ")",
    'insert industry_lines'
)

# 4. 红绿灯规则
run(
    "INSERT INTO tracking_rules (stock_code, dimension, indicator, red, yellow, green, sort_order) VALUES "
    "('605589.SH', '现金流质量', '经营现金流净额', '2026 全年仍为负且继续恶化', '收窄至 -5 亿以内', '转正', 0), "
    "('605589.SH', '竞争产能', 'PPO 高端树脂报价', '回落 30%+（东材/同宇放量冲击）', '报价持稳但新产能投产', '满产满销且报价坚挺', 1), "
    "('605589.SH', '利润兑现', '扣非同比（剔除股份支付）', '转负', '0-15%', '>15% 增长', 2)",
    'insert tracking_rules'
)

# 5. 波段纪律模块（swing 专属）
run(
    "INSERT INTO stock_modules (id, stock_code, module_key, title, template_key, sort_order, visible) VALUES "
    "(2444, '605589.SH', 'swing_discipline', '⚡ 波段纪律', '', 1, 1)",
    'insert stock_modules'
)
run(
    "INSERT INTO module_blocks (id, module_id, block_type, data_json, sort_order) VALUES "
    "(8963, 2444, 'callout', '{\"text\":\"**分类：技术短线（成长兑现型）**\\n\\n全球酚醛/呋喃树脂龙头（65 万吨/12 万吨、产销国内第一）+ 国内唯一千吨级电子级 PPO（国内份额约 70%、过英伟达/华为/台光/生益认证），多孔碳市占率前二。四层筛子 3/4：①格局壁垒过 ②价值量过（M6→M10 单价台阶）③供需短期过、2026-2029 国内新产能集中释放中期压力 ④弹性未兑现（2026H1 归母 -10.7%，剔除股份支付 +4.3%）。经营现金流连年为负（2026H1 -9.75 亿）扩张失血。成长兑现型 swing 非 core——升 core 条件：经营现金流转正 + 利润重回双位数增长 + 新产能爬坡验证。\",\"tone\":\"info\"}', 1), "
    "(8964, 2444, 'table', '{\"headers\":[\"信号\",\"条件\"],\"rows\":[[\"进场\",\"回调至 32-36 元（2027E 20-23x + PB 2.5-2.8）分批；26-30 元（PB 2.0-2.3 历史中枢）为舒服带\"],[\"止损\",\"跌破 22 元（PB<1.75），或三季报现金流继续恶化且利润转负增长\"],[\"止盈\",\"反弹至 50 元上方（2027E 乐观 28x）减仓，或 PE 冲高 >40x 后回落\"],[\"仓位上限\",\"≤5%（成长兑现波段仓）\"]]}', 2), "
    "(8965, 2444, 'callout', '{\"text\":\"**风险**：经营现金流连年负、2026H1 -9.75 亿历史最差 + 资产负债率 32.6%→41.3%（扩张失血）；PPO 新产能 2026-2029 集中释放（东材 2 万吨、同宇、银禧）；25 亿硅碳/多孔碳万吨级放大豪赌；情绪证伪先例（沙特断供系工程塑料级，公司澄清电子级价格稳定）；大庆生物质基地亏损；实控人父子质押率约 29%/46%；baolei 评级中（现金流质量+增收不增利双黄）。\",\"tone\":\"warn\"}', 3)",
    'insert module_blocks'
)

# 6. 验证
print('== 验证 ==')
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT code, name, category, pe_current, ttm_buy_range, buy_range_type FROM stocks WHERE code='605589.SH'")
print('stocks:', rows if ok else err)
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT line_id, position, weight, segment FROM industry_lines WHERE stock_code='605589.SH'")
print('lines:', rows if ok else err)
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT COUNT(*) AS n FROM module_blocks WHERE module_id=2444")
print('blocks:', rows if ok else err)
ok, rows, _m, err = cf_d1.execute_sql(db, "SELECT id, name, stage FROM industries WHERE id='electronic-resin'")
print('industries:', rows if ok else err)
