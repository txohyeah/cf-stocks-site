#!/usr/bin/env python3
"""横店东磁（002056.SZ）u4 详情迁移：催化节点 + 定位核验 + 升级降级 + 估值分析 + 风险提示
从 https://u4-stocks.xiaoxia.io/pages/002056 手动采集（u4 无 API，逐页人工迁移）。
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CODE = '002056.SZ'

def q(s): return str(s).replace("'", "''")

# ---------- 催化节点 ----------
CATALYSTS = [
    ('2026H2', 'AI 电感海外大客户转批量', '器件季度增速能否维持 50%+', 0),
    ('2026H2', '光伏价格企稳/行业出清', '组件招标价跌破 0.7 元/W，关注毛利率止跌', 1),
    ('2026 年报', 'SST 送样转批量订单', '公司称 2026 难成体量，若转批量即超预期', 2),
    ('2027', '锂电全极耳/21700 放量', '8.5GWh 产能利用率提升，毛利率续升', 3),
]

# ---------- 定位核验 · 为什么是前瞻卡位 ----------
POS_CHECK = {
    'title': '📌 定位核验 · 为什么是前瞻卡位',
    'blocks': [
        {'type': 'callout', 'tone': 'info', 'text':
         '🔭 前瞻卡位 A 级 —— 双卡位成立但分层兑现：AI 电感（器件 +86.5%）已规模化应用、是兑现中的 A 线；'
         'SST 已配套头部客户但公司明确 2026 难成实质体量，是 2028 免费期权；磁材现金牛 + 股息 4.56% 托底。'
         '光伏周期拖累（毛利率 11.18%），归母 -7%/扣非 -24% 经营实质弱于报表，现价 21 元合理偏上沿，回调分批。'},
        {'type': 'table', 'headers': ['双条件', '验证'], 'rows': [
            ['双条件 ① 卡住的位置，风没来',
             'SST（风没来、位已占）：高频软磁已向国内外头部 SST 客户配套供货（2025-10），磁芯为 SST 成本核心（中高频变压器占整机约 16%）；但产业 2026 元年、公司自认 2026 无实质体量 → 风未至、位已占'],
            ['双条件 ② 风要来的位置，卡住了',
             'AI 电感（风已来、位已占）：一体成型/铜铁共烧电感卡位 GPU/CPU 供电链路，已规模化应用于服务器（单机用量 8-10 倍、价值量 5-15 倍），AI 相关收入占软磁约 20%，2026H1 器件 +86.5% 验证'],
        ]},
        {'type': 'text', 'text':
         '🔍 判定三问 · 投入期亏损还是经营恶化？\n光伏主业是行业周期底部而非投入期亏损（H1 毛利率 11.18% 仍盈利，行业均值仅 0.67%）；'
         '但扣非 -24.3%、存货 64 亿(+54%)、现金流 -57% 是真实经营逆风。区分看：磁材/器件/锂电三线均在改善，'
         '光伏是周期性而非结构性恶化，汇兑（5.78 亿剪刀差）是波动项。'},
        {'type': 'table', 'headers': ['P/G/T', '判定', '依据'], 'rows': [
            ['P · 兑现可能性', 'P 高', 'AI 电感已规模化兑现（器件 +86.5%）；SST 配套导入初期，P 中'],
            ['G · 兑现后成长性', 'G 大', 'AI 电感单机价值量 5-15 倍、AI 服务器 2026 出货 +28%；SST 磁芯 2028 后规模化，单机材料价值量 5-10%'],
            ['T · 兑现节奏', 'T 1-2 年（AI 电感）/ 3 年+（SST）', 'AI 电感海外客户验证/小批量导入中；SST 公司明确 2026 无体量、2028 后规模化'],
        ]},
        {'type': 'callout', 'tone': 'good', 'text':
         '🎯 仓位含义（A 级）：A 级卫星仓 —— AI 电感兑现线 + 磁材现金牛底仓（股息 4.56% 垫底），SST 作免费期权不额外加仓。分批建仓区 17.5-21 元。'},
    ],
}

# ---------- 升级 / 降级信号 ----------
UP_DOWN = {
    'title': '🔭 升级 / 降级信号',
    'blocks': [
        {'type': 'title', 'text': '⬆️ 升级产业主脉信号（全部满足才换挡）'},
        {'type': 'table', 'headers': ['信号', '阈值', '状态'], 'rows': [
            ['器件收入增速', '连续两季 +50% 以上（AI 电感规模化放量）', '✅'],
            ['AI 收入占软磁比例', '从 20% 升至 30%+', '⚠️'],
            ['光伏毛利率', '环比回升至 13% 以上', '⚠️'],
        ]},
        {'type': 'title', 'text': '⬇️ 降级技术短线信号（任一触发即重估）'},
        {'type': 'table', 'headers': ['信号', '阈值', '状态'], 'rows': [
            ['光伏亏损', '毛利率跌破 8% 或单季亏损', '❌'],
            ['存货减值', '下半年补提大额减值（>3 亿）', '❌'],
            ['AI 电感客户验证停滞', '器件增速掉到 20% 以下', '❌'],
            ['汇兑持续侵蚀', '财务费用连续两季 >2.5 亿', '⚠️'],
        ]},
    ],
}

# ---------- 估值分析 ----------
VALUATION = {
    'title': '💰 估值分析',
    'blocks': [
        {'type': 'callout', 'tone': 'good', 'text':
         '🎯 结论：当前 21.14 元 / PE(TTM) 19.3x 处合理区中上部 —— 磁材+器件+锂电基本盘（股息 4.56% 垫底）+ '
         'AI 电感兑现中 + SST 2028 期权，可持有；扣非口径 PE 22.9x 偏贵，回调至 19 元以下再加仓'},
        {'type': 'text', 'text':
         '当前估值位置：21.14 元 / 344 亿 / PE(TTM) 19.3x（扣非 22.9x），近 250 日分位 76%（区间 12.8-30x，中位 15.2x）。\n'
         '估值方法：PE(TTM) 区间法（磁材器件主脉锚）+ AI 电感成长线 + SST 期权'},
        {'type': 'title', 'text': '📏 合理 TTM 依据（结合当前产业）'},
        {'type': 'text', 'text':
         '主脉：全球铁氧体磁材出货第一，2026H1 磁材+器件毛利 7.31 亿≈光伏 8.24 亿，利润结构从光伏单核转向多核；'
         '合理 15-22x PE(TTM)（成熟制造+4.56% 股息垫底）。AI 电感（器件 +86.5%）为兑现中成长线，SST 为 2028 期权（公司明确 2026 无实质体量）'},
        {'type': 'table', 'headers': ['区间', '价格', 'PE(TTM)'], 'rows': [
            ['低估区', '<16.4 元', 'PE(TTM)<15x'],
            ['合理区（当前）', '16.4-24 元', 'PE(TTM) 15-22x'],
            ['高估区', '>24 元', 'PE(TTM)>22x'],
        ]},
        {'type': 'text', 'text':
         '🔍 估值跟踪变量：器件/AI 电感季度增速与海外客户导入、SST 送样转批量节点、光伏毛利率能否守住 11%、'
         '存货减值与汇兑；AI 电感放量或光伏出清可上修至 25x'},
    ],
}

# ---------- 风险提示 ----------
RISK = {
    'title': '⚠️ 风险提示',
    'blocks': [
        {'type': 'callout', 'tone': 'warn', 'text':
         '光伏行业周期未见底：多晶硅致密料 52→32.5 元/kg、组件招标跌破 0.7 元/W、H1 组件产量 -35%；差异化溢价能守多久存疑'},
        {'type': 'callout', 'tone': 'warn', 'text':
         '存货 64.17 亿(+54%)、周转 106 天：H1 仅计提 0.63 亿减值，若价格续跌下半年补提风险'},
        {'type': 'callout', 'tone': 'warn', 'text':
         '海外收入占 47%，人民币升值汇兑持续压制利润（H1 财务费用 +2.64 亿 vs 去年 -3.14 亿）'},
        {'type': 'callout', 'tone': 'warn', 'text':
         '少数股东损益缓冲不可持续：2025H1 +2.94 亿 → 2026H1 -0.74 亿，光伏子公司亏损分担已反转'},
        {'type': 'callout', 'tone': 'warn', 'text':
         'SST 兑现节奏低于预期：公司明确 2026 年难形成实质体量，期权时间价值需耐心'},
    ],
}


def main():
    stmts = []
    stmts.append("-- 横店东磁 u4 详情迁移")
    stmts.append(f"DELETE FROM catalysts WHERE stock_code = '{CODE}';")
    for due, name, note, so in CATALYSTS:
        stmts.append(
            f"INSERT INTO catalysts (stock_code, name, due_date, status, note, sort_order) VALUES "
            f"('{CODE}', '{q(name)}', '{q(due)}', 'pending', '{q(note)}', {so});")

    stmts.append(f"DELETE FROM stock_modules WHERE stock_code = '{CODE}' AND template_key IN "
                 f"('positioning_check','upgrade_downgrade','valuation','risk');")
    for mod, tk in [(POS_CHECK, 'positioning_check'), (UP_DOWN, 'upgrade_downgrade'),
                     (VALUATION, 'valuation'), (RISK, 'risk')]:
        stmts.append(
            f"INSERT INTO stock_modules (stock_code, module_key, title, template_key, sort_order, visible) VALUES "
            f"('{CODE}', '{tk}', '{q(mod['title'])}', '{tk}', 2, 1);")
        for b in mod['blocks']:
            if b['type'] == 'table':
                payload = {'headers': b['headers'], 'rows': b['rows']}
            elif b['type'] == 'callout':
                payload = {'text': b['text'], 'tone': b['tone']}
            else:
                payload = {'text': b.get('text', '')}
            dj = json.dumps(payload, ensure_ascii=False)
            stmts.append(
                f"INSERT INTO module_blocks (module_id, block_type, data_json, sort_order) VALUES "
                f"(last_insert_rowid(), '{b['type']}', '{q(dj)}', 0);")

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', '002056_seed.sql')
    open(out, 'w').write('\n'.join(stmts) + '\n')
    print('OK →', out)


if __name__ == '__main__':
    main()