-- stocks 站点 D1 schema
-- 全站口令门禁：无匿名，未登录跳 /login
-- 角色：admin（唯一，可管理游客）/ guest（游客，管理员创建）

-- 用户与会话
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  passphrase_hash TEXT NOT NULL,          -- pbkdf2$iter$salt_b64$hash_b64
  role TEXT NOT NULL DEFAULT 'guest',     -- admin | guest
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 文章（相关文章总结）
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  summary TEXT DEFAULT '',
  content_md TEXT DEFAULT '',
  tags TEXT DEFAULT '',                    -- JSON 数组
  published INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 标的池（首版 = u4 145 只种子）
CREATE TABLE IF NOT EXISTS stocks (
  code TEXT PRIMARY KEY,                   -- 600519.SH
  name TEXT NOT NULL,
  sector TEXT DEFAULT '',
  category TEXT DEFAULT '',                -- core/frontier/swing/dividend/sunset
  subtype TEXT DEFAULT '',                 -- explosion/cashcow/...（core 细分）
  tags TEXT DEFAULT '',                    -- JSON 数组
  desc TEXT DEFAULT '',
  pe_current REAL,
  pe_date TEXT DEFAULT '',
  ttm_buy_range TEXT DEFAULT '',           -- JSON 数组 [12, 18]
  buy_range_type TEXT DEFAULT 'pe',
  tracked INTEGER NOT NULL DEFAULT 1,
  added_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_stocks_category ON stocks(category);

-- 行业模型（沿用 u4 48 行业 5 阶段）
CREATE TABLE IF NOT EXISTS industries (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  stage TEXT NOT NULL,                     -- boom/grow/seed/mature/decline
  summary TEXT DEFAULT '',
  segments TEXT DEFAULT '',                -- JSON 数组
  tags TEXT DEFAULT '',                    -- JSON 数组
  track_indicators TEXT DEFAULT ''         -- JSON 数组（红绿灯指标）
);

-- 个股产业线（多产线）
CREATE TABLE IF NOT EXISTS industry_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  line_id TEXT DEFAULT '',
  position TEXT DEFAULT '',                -- leader/challenger/follower
  weight TEXT DEFAULT '',                  -- primary/secondary
  segment TEXT DEFAULT '',
  note TEXT DEFAULT '',
  sort_order INTEGER DEFAULT 0,
  lineCat TEXT DEFAULT ''                  -- 行业线分类：mainline/frontier/explosion 等
);
CREATE INDEX IF NOT EXISTS idx_industry_lines_stock ON industry_lines(stock_code);

-- ★ 特殊模块 = 有序内容块（可扩展展现形式）
CREATE TABLE IF NOT EXISTS stock_modules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  module_key TEXT NOT NULL,                -- 如 milestone / governance / example
  title TEXT DEFAULT '',
  template_key TEXT DEFAULT '',            -- 固定模板：blocks 组合的快捷展开
  sort_order INTEGER DEFAULT 0,
  visible INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_stock_modules_stock ON stock_modules(stock_code);

CREATE TABLE IF NOT EXISTS module_blocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  module_id INTEGER NOT NULL,
  block_type TEXT NOT NULL,                -- title/text/chart/table/callout...
  data_json TEXT NOT NULL,                 -- 按 type 的 schema
  sort_order INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_module_blocks_module ON module_blocks(module_id);

-- 红绿灯跟踪（规则 + 最新值）
CREATE TABLE IF NOT EXISTS tracking_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  dimension TEXT DEFAULT '',
  indicator TEXT DEFAULT '',
  red TEXT DEFAULT '',
  yellow TEXT DEFAULT '',
  green TEXT DEFAULT '',
  sort_order INTEGER DEFAULT 0,
  current_light TEXT DEFAULT '',           -- 最新红绿灯：red/yellow/green
  current_note TEXT DEFAULT ''             -- 最新灯位说明
);
CREATE INDEX IF NOT EXISTS idx_tracking_rules_stock ON tracking_rules(stock_code);

CREATE TABLE IF NOT EXISTS tracking_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  dimension TEXT DEFAULT '',
  value TEXT DEFAULT '',
  as_of TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tracking_data_stock ON tracking_data(stock_code);

-- 催化节点（前瞻卡位跟踪）
CREATE TABLE IF NOT EXISTS catalysts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  name TEXT DEFAULT '',
  due_date TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',           -- pending/done/skipped
  note TEXT DEFAULT '',
  sort_order INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_catalysts_stock ON catalysts(stock_code);

-- PE(TTM) 历史（daily_basic 导出）
CREATE TABLE IF NOT EXISTS pe_history (
  stock_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  pe_ttm REAL,
  PRIMARY KEY (stock_code, trade_date)
);

-- ★ 暴雷检查（自动排雷：stock-analytics baolei 五雷区 + 深度检查）
-- 与人工手写的 module_key='risk'（⚠️ 风险提示）严格区分：这里是机器判定，不可手改
CREATE TABLE IF NOT EXISTS risk_checks (
  stock_code TEXT PRIMARY KEY,
  rating TEXT DEFAULT '',                  -- 综合筛查评级：低 / 中 / 高（五雷区 + 深度检查取严）
  rating_zone TEXT DEFAULT '',             -- 结构风险评级：低 / 中 / 高（仅五雷区口径）
  r0 TEXT DEFAULT '', r0_detail TEXT DEFAULT '',   -- 雷区零 审计意见（非标前置闸门）
  r1 TEXT DEFAULT '', r1_detail TEXT DEFAULT '',   -- 雷区一 利润结构（扣非/归母）
  r2 TEXT DEFAULT '', r2_detail TEXT DEFAULT '',   -- 雷区二 现金流质量
  r3 TEXT DEFAULT '', r3_detail TEXT DEFAULT '',   -- 雷区三 商誉（/归母净资产）
  r4 TEXT DEFAULT '', r4_detail TEXT DEFAULT '',   -- 雷区四 业绩拐点
  deep_json TEXT DEFAULT '[]',             -- 深度检查项 JSON [{name,level,detail}]
  reasons TEXT DEFAULT '[]',               -- 触发项汇总 JSON（空 = 全绿）
  as_of TEXT DEFAULT '',                   -- 最新报告期（数据截止）
  checked_at TEXT DEFAULT ''               -- 检查时间
);
-- ★ 宏观：数据发布日历（2026-09-16 新增，源：stock-analytics macro_calendar / tushare eco_cal）
-- 含**未来已排期**行（value 为空 = 尚未公布），公布后由 sync_macro.py 幂等补上实际值
CREATE TABLE IF NOT EXISTS macro_calendar (
  date TEXT NOT NULL,                      -- YYYYMMDD
  time TEXT NOT NULL DEFAULT '',           -- HH:MM（东八区）
  event TEXT NOT NULL,                     -- 以"中国"开头（境外错标行已在源头过滤）
  value TEXT,                              -- 原始字符串（带单位后缀，如 1,660.0B）
  fore_value TEXT,                         -- 市场预期（原始字符串）
  pre_value TEXT,                          -- 上月实际（原始字符串；数据源偶有脏行）
  value_num REAL,                          -- 解析后数值（事件自身单位）
  fore_num REAL,
  pre_num REAL,
  surprise REAL,                           -- value_num - fore_num（预期差）
  unit TEXT DEFAULT '',                    -- B=十亿 / T=万亿 / M=百万 / %=百分点 / ''=原值
  -- 参照系列（2026-09-16 晚新增；由 sync_macro.py 按"数据月份"对齐算出，非数据源字段）
  ref_yoy REAL,                            -- 去年同期值（同月对齐，不按发布日期）
  ref_yoy_diff REAL,                       -- 本期 − 去年同期（金额口径=金额差；% 口径=百分点差）
  ref_yoy_pct REAL,                        -- 变化率%（仅金额口径；% 口径为 NULL，避免"同比的同比"）
  ref_avg5 REAL,                           -- 历年同期均值（前 1~5 年同月，≥3 年才给）
  ref_avg5_n INTEGER,                      -- 参与均值的年数
  pct_rank REAL,                           -- 近 12 期分位：升序中"≤本期"的期数 ÷ 期数（越大越强）
  pct_rank_n INTEGER,                      -- 分位窗口实际期数（<6 期不给分位）
  PRIMARY KEY (date, time, event)
);
-- ⚠️ 明确不做环比（mom）：社融/信贷/CPI 季节性极强，环比会系统性误导（要看季节性用 ref_avg5）
-- 已建库的存量升级（一次性；D1 报 duplicate column 即已升过）：
--   ALTER TABLE macro_calendar ADD COLUMN ref_yoy REAL;
--   ALTER TABLE macro_calendar ADD COLUMN ref_yoy_diff REAL;
--   ALTER TABLE macro_calendar ADD COLUMN ref_yoy_pct REAL;
--   ALTER TABLE macro_calendar ADD COLUMN ref_avg5 REAL;
--   ALTER TABLE macro_calendar ADD COLUMN ref_avg5_n INTEGER;
--   ALTER TABLE macro_calendar ADD COLUMN pct_rank REAL;
--   ALTER TABLE macro_calendar ADD COLUMN pct_rank_n INTEGER;
CREATE INDEX IF NOT EXISTS idx_macro_cal_date ON macro_calendar(date);

-- ★ 宏观：解读笔记（2026-09-16 晚新增，b 档"我定期写"层）
-- 页面上分两层：**自动判定层**（macro_conditions 体检卡，每天由 sync_macro.py 刷新）
-- 与 **解读笔记层**（本表，由 agent cron 在"当天有数据发布"时写入，带撰写时间戳）。
-- 写笔记的工具：scripts/macro_note.py（check 判断今天有没有新发布 / save 落库）
CREATE TABLE IF NOT EXISTS macro_notes (
  note_date TEXT NOT NULL,                 -- 归属日期 YYYYMMDD（= 数据发布日或周记日）
  kind TEXT NOT NULL DEFAULT 'release',    -- release=数据发布解读 / weekly=周记 / regime=当前宏观定性（只在定性变化时新增，规则层写）
  created_at TEXT NOT NULL,                -- 撰写时间（页面显示"最后更新于"）
  title TEXT DEFAULT '',
  body_md TEXT NOT NULL,                   -- 正文（轻量 markdown：段落 / - 列表 / **加粗**）
  covered TEXT DEFAULT '',                 -- 覆盖的发布事件（逗号分隔，便于回溯）
  as_of TEXT DEFAULT '',                   -- 数据口径截点（YYYYMMDD）
  source TEXT DEFAULT 'agent',             -- agent=模型撰写 / human=人工撰写
  PRIMARY KEY (note_date, kind)
);

-- ★ 宏观 → 产业 传导（2026-09-16 晚新增；规则表在 scripts/macro_industry.json）
-- 每个产业一行：当前宏观环境对它偏顺风还是偏逆风 + 逐条驱动项（实测值/规则/理由）。
-- 定位：只做**方向判定**，不映射到个股买卖；产业自身的红绿灯仍在 /industries。
CREATE TABLE IF NOT EXISTS macro_industry_state (
  industry_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  link TEXT DEFAULT '',                    -- 传导链条的一句话描述
  state_kind TEXT DEFAULT 'mixed',         -- favorable / unfavorable / mixed
  state_text TEXT DEFAULT '',              -- 如"偏顺风（2 顺 / 1 逆）"
  favorable INTEGER DEFAULT 0,
  unfavorable INTEGER DEFAULT 0,
  drivers_json TEXT DEFAULT '[]',          -- [{label,value_text,side,rule,note,date}]
  updated_at TEXT
);

-- ★ 宏观：月度/季度序列（长表：一个指标一行，加指标不用改 schema）
-- indicator：社融增量 / 社融存量 / M1同比 / M2同比 / M1M2剪刀差 / CPI同比 / PPI同比 / GDP同比
CREATE TABLE IF NOT EXISTS macro_series (
  month TEXT NOT NULL,                     -- YYYYMM（GDP 用 YYYYQn）
  indicator TEXT NOT NULL,
  value REAL,
  unit TEXT DEFAULT '',
  PRIMARY KEY (month, indicator)
);

-- ★ 宏观：日频（资金面/杠杆资金）—— indicator：Shibor隔夜 / 两融余额 / 北向净买
CREATE TABLE IF NOT EXISTS macro_daily (
  trade_date TEXT NOT NULL,
  indicator TEXT NOT NULL,
  value REAL,
  unit TEXT DEFAULT '',
  PRIMARY KEY (trade_date, indicator)
);
CREATE INDEX IF NOT EXISTS idx_macro_daily_date ON macro_daily(trade_date);

-- ★ 宏观：框架条件变量体检（2026-09-16 新增）
-- 来源 = 文章 /article/investment-framework 第 1 节定义的条件变量 + 宏观页自测补充项，
-- 由 sync_macro.py 每次同步**整体重算**（含 auto 库内数据与 manual 手工新闻事实）。
-- status_kind：ok 达成 / warn 观察 / bad 反向 / gap 无数据源
CREATE TABLE IF NOT EXISTS macro_conditions (
  cond_key TEXT PRIMARY KEY,               -- 稳定键（如 oil_30d_95），页面按 sort_order 展示
  title TEXT NOT NULL,                     -- 条件名
  target_text TEXT DEFAULT '',             -- 条件定义（文章原文口径）
  current_text TEXT DEFAULT '',            -- 当前实测（数字/日期）
  status_kind TEXT DEFAULT 'warn',         -- ok / warn / bad / gap
  status_text TEXT DEFAULT '',             -- 状态徽章文字
  source TEXT DEFAULT '',                  -- 数据来源（自动/手工分别标注）
  source_kind TEXT DEFAULT 'auto',         -- auto（库内每日自动）/ manual（手工录入）
  note TEXT DEFAULT '',                    -- 补充说明
  sort_order INTEGER DEFAULT 0,
  updated_at TEXT
);
