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
  sort_order INTEGER DEFAULT 0
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
  sort_order INTEGER DEFAULT 0
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