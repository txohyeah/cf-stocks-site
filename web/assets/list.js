/* 个股列表页 v3：7 分类 + 6 产线筛选 + 48 产业下拉 + 顶部产业定位说明 */
const CATS = [
  ['', '全部'],
  ['recent', '🆕 最近24h'],
  ['core', '🏭 产业主脉'],
  ['frontier', '🔮 前瞻卡位'],
  ['swing', '⚡ 技术短线'],
  ['dividend', '💎 分红企业'],
  ['sunset', '🌇 夕阳龙头'],
  ['explosion', '🔥 产业爆发'],
];
const CAT_EMOJI = { core: '🏭', frontier: '🔮', swing: '⚡', dividend: '💎', sunset: '🌇' };
const LINE_FILTERS = [
  ['', '全部产线'],
  ['mainline', '🏭 含主脉线'],
  ['frontier', '🔮 含卡位线'],
  ['swing', '⚡ 含短线线'],
  ['dividend', '💎 含分红线'],
  ['sunset', '🌇 含夕阳线'],
  ['explosion', '🔥 含爆发线'],
];
/* 顶部产业定位说明（折叠展开） */
const POSITION_GUIDE = [
  ['🏭 产业主脉', '产业已验证 + 公司卡住核心位置 — 四层筛子通过，产业趋势清晰可跟踪。适合在特定 PE 区间内买入并长持。'],
  ['🔮 前瞻卡位', '产业方向已确立，兑现尚在途中 — 公司已卡准产业链位置，但产业本身未到商业化拐点。产业成熟后自动升级为产业主脉。'],
  ['⚡ 技术短线', '非产业主脉、非前瞻卡位、非高分红企业 — 借产业外溢订单或题材轮动获益，公司自身稀缺性或稳定性不足，适合波段操作而非产业长持。'],
  ['💎 分红企业', '每年股息率 2% 以上，市值大、波动稳 — 成熟的现金奶牛，适合作为底仓配置长期持有，PE 合理时买入。'],
  ['🌇 夕阳龙头', '产业趋势性萎缩 + 公司仍卡住核心位置 — 质地顶级但产业总量下移（白酒等），估值中枢长期承压。只做波段 + 吃股息，不建长持仓；产业指标（如批价）跌破阈值即价值陷阱。'],
];

let stocks = [];
let allStocks = [];   // 全量缓存：标签计数基准（不随筛选变化）
let industries = [];
let activeCat = '';
let activeLine = '';
let activeInd = '';
let q = '';

async function me() {
  try {
    const r = await fetch('/api/me');
    const d = await r.json();
    if (!d.authed) { location.href = '/login'; return null; }
    const who = document.getElementById('who');
    who.textContent = d.username + (d.role === 'admin' ? ' · 管理员' : '');
    if (d.role === 'admin') document.getElementById('admin-link').hidden = false;
    return d;
  } catch (e) { location.href = '/login'; return null; }
}

function renderGuide() {
  const el = document.getElementById('pos-guide');
  el.innerHTML = `<details class="pos-guide"><summary>🏷️ 个股产业定位说明（6 类）</summary>
    <div class="pg-list">${POSITION_GUIDE.map(([t, d]) =>
      `<div class="pg-item"><b>${esc(t)}</b> <span>${esc(d)}</span></div>`).join('')}
    </div>
    <p class="pg-more"><a href="/article/positioning-guide">查看完整说明 →</a></p></details>`;
}

async function loadIndustries() {
  const r = await fetch('/api/industries');
  const d = await r.json();
  if (!d.ok) return;
  industries = d.industries || [];
  const sel = document.getElementById('ind-select');
  sel.innerHTML = '<option value="">🏭 全部产业</option>' + industries.map(x =>
    `<option value="${esc(x.id)}">${esc(x.name)}（${STAGE_LABEL[x.stage] || x.stage}）</option>`).join('');
}

async function load() {
  // 首次加载时拉一次全量列表作为标签计数基准（不随筛选变化）
  if (!allStocks.length) {
    const r0 = await fetch('/api/stocks');
    const d0 = await r0.json();
    if (!d0.ok) { location.href = '/login'; return; }
    allStocks = d0.stocks;
  }
  const params = new URLSearchParams();
  if (activeCat === 'recent') params.set('recent', '1');
  else if (activeCat && activeCat !== 'explosion') params.set('category', activeCat);
  if (activeCat === 'explosion' || activeLine) params.set('lineCat', activeCat === 'explosion' ? 'explosion' : activeLine);
  if (activeInd) params.set('industry', activeInd);
  if (q) params.set('q', q);
  const r = await fetch('/api/stocks?' + params.toString());
  const d = await r.json();
  if (!d.ok) { location.href = '/login'; return; }
  stocks = d.stocks;
  renderTabs();
  renderLineFilter();
  renderCards();
}

function renderTabs() {
  const el = document.getElementById('cat-filters');
  el.innerHTML = '';
  for (const [val, label] of CATS) {
    let n;
    if (!val) n = allStocks.length;
    else if (val === 'recent') n = allStocks.filter(s => (s.added_at || '') >= recentCutoff()).length;
    else if (val === 'explosion') n = allStocks.filter(s => (s.lines || []).some(l => l.lineCat === 'explosion')).length;
    else n = allStocks.filter(s => s.category === val).length;
    const btn = document.createElement('button');
    btn.className = 'tab' + (val === activeCat ? ' active' : '');
    btn.innerHTML = label + '<span class="n">' + n + '</span>';
    btn.onclick = () => { activeCat = val; load(); };
    el.appendChild(btn);
  }
}

// 东八区 24h 前时间 'YYYY-MM-DD HH:MM:SS'（与 worker 过滤口径一致）
function recentCutoff() {
  const off = 8 * 3600 * 1000;
  return new Date(Date.now() - 86400000 + off).toISOString().slice(0, 19).replace('T', ' ');
}

function renderLineFilter() {
  const el = document.getElementById('line-filters');
  el.innerHTML = '';
  for (const [val, label] of LINE_FILTERS) {
    let n;
    if (!val) n = allStocks.length;
    else n = allStocks.filter(s => (s.lines || []).some(l => l.lineCat === val)).length;
    const btn = document.createElement('button');
    btn.className = 'tab' + (val === activeLine ? ' active' : '');
    btn.innerHTML = label + '<span class="n">' + n + '</span>';
    btn.onclick = () => { activeLine = val; load(); };
    el.appendChild(btn);
  }
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}
function fmtTags(tags) {
  try { return JSON.parse(tags || '[]'); } catch (e) { return []; }
}
function fmtMv(v) { return v == null || isNaN(v) ? '—' : (Number(v) / 10000).toFixed(0) + '亿'; }

async function renderCards() {
  const grid = document.getElementById('stock-grid');
  const cnt = document.getElementById('stock-count');
  const subtitle = [
    activeCat ? (CATS.find(x => x[0] === activeCat) || [])[1] : '',
    activeLine ? (LINE_FILTERS.find(x => x[0] === activeLine) || [])[1] : '',
    activeInd ? (industries.find(x => x.id === activeInd) || {}).name || '' : ''
  ].filter(Boolean).join(' · ');
  cnt.textContent = '共 ' + stocks.length + ' 只' + (subtitle ? '（' + subtitle + '）' : '');

  // 拉取每只最新 3 项（市值/股息率/换手率）——批量明细接口太重，仅显示 PE/分类/产线徽章
  grid.innerHTML = '';
  if (!stocks.length) {
    grid.innerHTML = '<div class="empty">没有符合条件的标的</div>';
    return;
  }
  for (const s of stocks) {
    const card = document.createElement('div');
    card.className = 'card';
    const catLabel = (CAT_EMOJI[s.category] ? CAT_EMOJI[s.category] + ' ' : '') +
      ((CATS.find(x => x[0] === s.category) || [])[1] || s.category || '—');
    const catCls = s.category ? 'cat-' + s.category : '';
    // 区间口径由 buy_range_type 决定：price=元，pe/pe-fwd/pe-core/pb/ps=倍数
    const buyRange = (() => {
      try {
        const a = JSON.parse(s.ttm_buy_range || '[]');
        if (!Array.isArray(a) || a.length !== 2 || !(Number(a[0]) || Number(a[1]))) return { text: '—', tip: '' };
        const unit = s.buy_range_type === 'price' ? '元' : 'x';
        return {
          text: Number(a[0]) + '~' + Number(a[1]) + unit,
          tip: RANGE_TIP[s.buy_range_type] || '合理估值区间'
        };
      } catch (e) { return { text: '—', tip: '' }; }
    })();
    const lineBadges = (s.lines || []).map(l => l.lineCat).filter(Boolean);
    const lineStr = ['mainline', 'frontier', 'explosion', 'swing', 'dividend', 'sunset']
      .filter(k => lineBadges.includes(k)).map(k => LINECAT_SHORT[k]).join(' ');
    card.innerHTML = `
      <div class="card-head">
        <div><span class="card-name">${esc(s.name)}</span> <span class="card-code">${esc(s.code)}</span></div>
        <span class="badge ${catCls}">${catLabel}</span>
      </div>
      <div class="card-sector">${esc(s.sector)}${s.subtype ? ' <span class="badge">' + esc(s.subtype) + '</span>' : ''}</div>
      ${lineStr ? `<div class="card-lines">${esc(lineStr)}</div>` : ''}
      <div class="card-desc">${esc(s.desc || '')}</div>
      <div class="card-meta">
        <span>PE(TTM) <b>${s.pe_current != null ? Number(s.pe_current).toFixed(2) : '—'}</b></span>
        <span title="${esc(buyRange.tip)}">合理区间 <b>${buyRange.text}</b></span>
      </div>
      <div class="card-badges">${fmtTags(s.tags).slice(0, 5).map(t => '<span class="badge">' + esc(t) + '</span>').join('')}</div>`;
    card.onclick = () => { location.href = '/stocks/' + s.code; };
    grid.appendChild(card);
  }
}

const LINECAT_SHORT = { mainline: '🏭主脉', frontier: '🔮卡位', explosion: '🔥爆发', swing: '⚡短线', dividend: '💎分红', sunset: '🌇夕阳' };
// ttm_buy_range 是「合理估值带」，不是买点：现价<下沿=低估、带内=合理、>上沿=高估。
// 值本身无单位，口径由 buy_range_type 决定，渲染时必须据此加单位。
const RANGE_TIP = {
  price: '合理价格区间（元）：现价低于下沿为低估，高于上沿为高估',
  pe: '合理 PE(TTM) 区间（倍）：现价 PE 低于下沿为低估',
  'pe-fwd': '合理前瞻 PE 区间（倍）',
  'pe-core': '合理 PE 区间（倍，core 口径）',
  pb: '合理 PB 区间（倍）',
  ps: '合理 PS 区间（倍）'
};
const STAGE_LABEL = { boom: '爆发', grow: '成长', seed: '萌芽', mature: '成熟', decline: '衰退' };

document.getElementById('search').addEventListener('input', (e) => {
  q = e.target.value.trim();
  load();
});
document.getElementById('ind-select').addEventListener('change', (e) => {
  activeInd = e.target.value;
  load();
});
document.getElementById('logout-btn').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  location.href = '/login';
});

(async () => {
  const u = await me();
  if (!u) return;
  renderGuide();
  await loadIndustries();
  await load();
})();