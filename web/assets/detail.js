/* 详情页 v3：u4 对齐 —— 头部 9 项指标 + PE 3年分位图 + 红绿灯矩阵 + 产业定位(u4格式) + 内容块 */
const CODE = decodeURIComponent(location.pathname.slice('/stocks/'.length));
const CATS = {
  core:      { label: '产业主脉', emoji: '🏭' },
  frontier:  { label: '前瞻卡位', emoji: '🔮' },
  swing:     { label: '技术短线', emoji: '⚡' },
  dividend:  { label: '分红企业', emoji: '💎' },
  sunset:    { label: '夕阳龙头', emoji: '🌇' },
};
const TEMPLATES = {
  core:     ['pe', 'valuation', 'risk', 'tracking', 'lines', 'poscheck', 'catalysts', 'modules'],
  frontier: ['pe', 'valuation', 'risk', 'tracking', 'lines', 'poscheck', 'catalysts', 'modules'],
  swing:    ['lines', 'risk', 'discipline'],
  dividend: ['dividend', 'pe', 'valuation', 'risk', 'tracking', 'lines', 'poscheck', 'catalysts', 'modules'],
  sunset:   ['pe', 'valuation', 'risk', 'tracking', 'lines', 'poscheck', 'catalysts', 'modules'],
};
const DEFAULT_TPL = ['pe', 'valuation', 'risk', 'lines', 'poscheck', 'tracking', 'modules', 'catalysts'];
const TITLES = {
  pe: '📈 估值 · PE(TTM)',
  valuation: '🧮 估值组成',
  risk: '🛡️ 暴雷检查',
  lines: '🏷️ 产业定位',
  poscheck: '📌 定位核验',
  modules: '📦 重点内容',
  tracking: '🚦 红绿灯跟踪',
  catalysts: '🎯 催化节点',
  dividend: '💎 分红',
  discipline: '⚡ 波段纪律',
};
const POS_LABEL = { leader: '龙头', core: '核心', minor: '次要', satellite: '卫星', optional: '期权' };
const WEIGHT_LABEL = { primary: '主', secondary: '次', tertiary: '三级', optional: '期权' };
const LINECAT_LABEL = {
  mainline: '🏭主脉线', frontier: '🔮卡位线', swing: '⚡短线线',
  dividend: '💎分红线', sunset: '🌇夕阳线', explosion: '🔥爆发线'
};
const STAGE_LABEL = { boom: '爆发', grow: '成长', seed: '萌芽', mature: '成熟', decline: '衰退' };
const DIM_META = {
  close:          { label: '收盘价', fmt: v => num(v, 2) },
  pe_lyr:         { label: 'PE(LYR)', fmt: v => num(v, 2) },
  pe_ttm:         { label: 'PE(TTM)', fmt: v => num(v, 2) },
  pb:             { label: 'PB', fmt: v => num(v, 2) },
  dv_ratio:       { label: '股息率', fmt: v => num(v, 2) + '%' },
  total_mv:       { label: '总市值', fmt: fmtMv },
  circ_mv:        { label: '流通市值', fmt: fmtMv },
  turnover_rate:  { label: '换手率', fmt: v => num(v, 2) + '%' },
  volume_ratio:   { label: '量比', fmt: v => num(v, 2) },
};
const HEAD_DIMS = ['pe_ttm', 'pe_lyr', 'pb', 'total_mv', 'circ_mv', 'turnover_rate', 'volume_ratio', 'dv_ratio', 'close'];

function esc(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}
function fmtDate(s) { return s ? String(s).replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3') : '—'; }
function num(v, d = 2) { return v == null || isNaN(v) ? '—' : Number(v).toFixed(d); }
function fmtMv(v) { return v == null || isNaN(v) ? '—' : (Number(v) / 10000).toFixed(0) + '亿'; }
function pctRank(sorted, p) {
  if (!sorted.length) return null;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(p * (sorted.length - 1))));
  return sorted[idx];
}

async function me() {
  try {
    const r = await fetch('/api/me');
    const d = await r.json();
    if (!d.authed) { location.href = '/login'; return null; }
    document.getElementById('who').textContent = d.username;
    return d;
  } catch (e) { location.href = '/login'; return null; }
}

/* ---------- 头部 ---------- */
function renderHead(s, data) {
  const cat = CATS[s.category] || { label: s.category || '未分类', emoji: '🏷️' };
  const tags = (() => { try { return JSON.parse(s.tags || '[]'); } catch (e) { return []; } })();
  const buyRange = (() => { try { const a = JSON.parse(s.ttm_buy_range || '[]'); return a.length === 2 ? a : null; } catch (e) { return null; } })();
  const dm = {};
  for (const t of data || []) dm[t.dimension] = t.value;
  const metrics = HEAD_DIMS.filter(k => dm[k] != null).map(k => {
    const meta = DIM_META[k] || { label: k, fmt: v => esc(v) };
    return `<div class="metric"><div class="m-label">${meta.label}</div><div class="m-val">${meta.fmt(dm[k])}</div><div class="m-date">${fmtDate((data || []).find(t => t.dimension === k)?.as_of || '')}</div></div>`;
  }).join('');
  return `
    <div class="detail-head">
      <div class="dh-top">
        <h1>${cat.emoji} ${esc(s.name)} <span class="code">${esc(s.code)}</span></h1>
        <span class="badge cat-${esc(s.category || '')}">${cat.label}</span>
      </div>
      <div class="dh-tags">
        <span class="badge">${esc(s.sector || '')}</span>
        ${s.subtype ? `<span class="badge">${esc(s.subtype)}</span>` : ''}
        ${tags.map(t => `<span class="badge">${esc(t)}</span>`).join('')}
      </div>
      ${s.desc ? `<p class="dh-desc">${esc(s.desc)}</p>` : ''}
      <div class="dh-metrics">${metrics}</div>
    </div>`;
}

/* ---------- PE 图（3 年 + 分位统计） ---------- */
function peChartSVG(pe, buyRange) {
  if (!pe || pe.length < 2) return '<p class="empty-sm">暂无 PE 历史数据</p>';
  const W = 1000, H = 320, PAD = 52, TOP = 16;
  const vals = pe.map(p => p.pe_ttm);
  let y0 = Math.min.apply(null, vals), y1 = Math.max.apply(null, vals);
  const buf = ((y1 - y0) * 0.12) || 1;
  y0 -= buf; y1 += buf;
  if (buyRange && buyRange.length === 2 && buyRange[1] > y1) y1 = buyRange[1] + buf;
  if (buyRange && buyRange.length === 2 && buyRange[0] < y0) y0 = buyRange[0] - buf;
  const x = i => PAD + i * (W - PAD - 16) / (pe.length - 1);
  const y = v => H - PAD - (v - y0) / (y1 - y0) * (H - PAD - TOP - 12);
  const path = pe.map((p, i) => (i === 0 ? 'M' : 'L') + x(i).toFixed(1) + ' ' + y(p.pe_ttm).toFixed(1)).join(' ');
  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const v = y0 + (y1 - y0) * i / 4;
    const yy = y(v);
    grid += `<line x1="${PAD}" y1="${yy.toFixed(1)}" x2="${W - 16}" y2="${yy.toFixed(1)}" stroke="#2e3a49" stroke-width="1"/>
      <text x="${PAD - 8}" y="${(yy + 4).toFixed(1)}" fill="#8b98a9" font-size="11" text-anchor="end">${num(v, 1)}</text>`;
  }
  let xlabels = '';
  const idxs = [0, Math.floor((pe.length - 1) / 2), pe.length - 1];
  for (const i of idxs) {
    xlabels += `<text x="${x(i).toFixed(1)}" y="${H - PAD + 18}" fill="#8b98a9" font-size="11" text-anchor="middle">${fmtDate(pe[i].trade_date)}</text>`;
  }
  let band = '';
  if (buyRange && buyRange.length === 2) {
    const yLo = y(buyRange[0]), yHi = y(buyRange[1]);
    band = `<rect x="${PAD}" y="${yHi.toFixed(1)}" width="${W - PAD - 16}" height="${Math.abs(yLo - yHi).toFixed(1)}" fill="rgba(63,185,80,.14)" stroke="rgba(63,185,80,.4)" stroke-dasharray="4 3"/>
      <text x="${W - 18}" y="${((yHi + yLo) / 2 + 4).toFixed(1)}" fill="#57d368" font-size="11" text-anchor="end">买入区间 ${num(buyRange[0])}~${num(buyRange[1])}</text>`;
  }
  const last = pe[pe.length - 1];
  const lastX = x(pe.length - 1), lastY = y(last.pe_ttm);
  const dot = `<circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="4" fill="#4c9aff"/>
    <text x="${(lastX - 8).toFixed(1)}" y="${(lastY - 10).toFixed(1)}" fill="#79b8ff" font-size="12" text-anchor="end" font-weight="700">${num(last.pe_ttm)}</text>`;
  const sorted = vals.slice().sort((a, b) => a - b);
  const med = pctRank(sorted, 0.5), p20 = pctRank(sorted, 0.2), p80 = pctRank(sorted, 0.8);
  const info = `区间: ${fmtDate(pe[0].trade_date)} ~ ${fmtDate(last.trade_date)} | PE中位数: ${num(med, 1)}x | 20%~80%区间: ${num(p20, 1)}x ~ ${num(p80, 1)}x | 当前: ${num(last.pe_ttm, 1)}x`;
  return `<div class="pe-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    ${grid}${xlabels}${band}
    <path d="${path}" fill="none" stroke="#4c9aff" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
    ${dot}
  </svg><p class="chart-info">${info}</p></div>`;
}

/* ---------- 产业定位（u4 格式） ---------- */
function renderLines(d) {
  if (!d.lines || !d.lines.length) return '<p class="empty-sm">暂无产业线数据</p>';
  return `<div class="line-list">${d.lines.map(l => `
    <div class="line-card">
      <div class="lc-top">
        <b>${l.line_name ? `<a href="/industry/${encodeURIComponent(l.line_id)}">${esc(l.line_name)} →</a>` : esc(l.segment || l.line_id || '—')}</b>
        <span class="lc-badges">
          ${l.position ? `<span class="badge pos-${esc(l.position)}">${POS_LABEL[l.position] || esc(l.position)}</span>` : ''}
          ${l.weight ? `<span class="badge">${WEIGHT_LABEL[l.weight] || esc(l.weight)}</span>` : ''}
          ${l.lineCat ? `<span class="badge lc">${LINECAT_LABEL[l.lineCat] || esc(l.lineCat)}</span>` : ''}
          ${l.line_stage ? `<span class="badge stage-${esc(l.line_stage)}">${STAGE_LABEL[l.line_stage] || esc(l.line_stage)}</span>` : ''}
        </span>
      </div>
      ${l.segment ? `<div class="lc-seg">环节：${esc(l.segment)}</div>` : ''}
      ${l.note ? `<p class="lc-note">${esc(l.note)}</p>` : ''}
    </div>`).join('')}</div>`;
}

/* ---------- 内容块 ---------- */
function renderBlock(b) {
  const d = b.data || {};
  switch (b.type) {
    case 'title': return `<h4 class="blk-title">${esc(d.text || '')}</h4>`;
    case 'text': return `<p class="blk-text">${esc(d.text || '').replace(/\n/g, '<br>')}</p>`;
    case 'callout': {
      const tone = ['warn', 'good', 'info'].includes(d.tone) ? d.tone : 'info';
      return `<div class="callout callout-${tone}">${esc(d.text || '').replace(/\n/g, '<br>')}</div>`;
    }
    case 'table': {
      const hd = Array.isArray(d.headers) ? d.headers : [];
      const rows = Array.isArray(d.rows) ? d.rows : [];
      if (!hd.length) return '';
      return `<div class="blk-table-wrap"><table class="blk-table"><thead><tr>${hd.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r => `<tr>${hd.map((_, ci) => `<td>${esc(r[ci] == null ? '' : r[ci])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    }
    case 'chart': {
      const labels = Array.isArray(d.labels) ? d.labels : [];
      const values = Array.isArray(d.values) ? d.values : [];
      const max = Math.max.apply(null, values.concat([1]));
      return `<div class="blk-chart">${labels.map((lb, i) => `
        <div class="bc-row"><span class="bc-label">${esc(lb)}</span>
          <div class="bc-bar-bg"><div class="bc-bar" style="width:${(values[i] / max * 100).toFixed(1)}%"></div></div>
          <span class="bc-val">${esc(values[i])}</span></div>`).join('')}</div>`;
    }
    default: return '';
  }
}

function renderModules(d) {
  const mods = (d.modules || []).filter(m => m.visible !== 0 && m.module_key !== 'positioning_check' && m.module_key !== 'swing_discipline' && m.module_key !== 'valuation');
  if (!mods.length) return null;
  // 每个模块独立成一个 section（标题 = 模块标题），不再挤在一个「重点内容」里
  return mods.map(m => `
    <section class="dsec">
      <h2>${esc(m.title || m.module_key)}</h2>
      <div class="module-card"><div class="mc-body">${(m.blocks || []).map(renderBlock).join('')}</div></div>
    </section>`).join('');
}

function renderDiscipline(d) {
  const m = (d.modules || []).find(x => x.module_key === 'swing_discipline' && x.visible !== 0);
  if (!m) return null;
  return `<div class="module-card">
    <div class="mc-head">${esc(m.title || '⚡ 波段纪律')}</div>
    <div class="mc-body">${(m.blocks || []).map(renderBlock).join('')}</div>
  </div>`;
}

function renderValuation(d) {
  const m = (d.modules || []).find(x => x.module_key === 'valuation' && x.visible !== 0);
  if (!m) return null;
  return `<div class="module-card">
    <div class="mc-body">${(m.blocks || []).map(renderBlock).join('')}</div>
  </div>`;
}

function renderPosCheck(d) {
  const m = (d.modules || []).find(x => x.module_key === 'positioning_check' && x.visible !== 0);
  if (!m) return null;
  return `<div class="module-card">
    <div class="mc-head">${esc(m.title || '📌 定位核验')}</div>
    <div class="mc-body">${(m.blocks || []).map(renderBlock).join('')}</div>
  </div>`;
}

/* ---------- 🛡️ 暴雷检查（自动排雷：stock-analytics baolei 五雷区 + 深度） ---------- */
const RISK_LIGHT_CLS = { '绿': 'green', '黄': 'yellow', '红': 'red', 'sk': 'gray' };
const RISK_LIGHT_EMOJI = { '绿': '🟢', '黄': '🟡', '红': '🔴', 'sk': '➖' };
// sk = baolei 判定"数据不足、跳过该项"（不是风险信号），显示成人话而非原始代号
const RISK_LIGHT_LABEL = { 'sk': '数据不足' };
const RISK_RATING_CLS = { '低': 'low', '中': 'mid', '高': 'high' };
const RISK_ZONES = [
  ['r0', '雷区零 · 审计意见', 'r0_detail'],
  ['r1', '雷区一 · 利润结构', 'r1_detail'],
  ['r2', '雷区二 · 现金流质量', 'r2_detail'],
  ['r3', '雷区三 · 商誉', 'r3_detail'],
  ['r4', '雷区四 · 业绩拐点', 'r4_detail'],
];

function riskLight(v) {
  const cls = RISK_LIGHT_CLS[v] || 'gray';
  const label = RISK_LIGHT_LABEL[v] || v || '—';
  return `<span class="badge light-${cls}">${RISK_LIGHT_EMOJI[v] || '⚪'} ${esc(label)}</span>`;
}

function renderRisk(d) {
  const r = d.risk;
  if (!r) return '<p class="empty-sm">暂无暴雷检查数据（该股未纳入自动排雷扫描，或财务数据不足）</p>';

  const zone = r.rating_zone || '—';
  const comp = r.rating || '—';
  const zoneCls = RISK_RATING_CLS[zone] || 'mid';
  const compCls = RISK_RATING_CLS[comp] || 'mid';
  let deep = [];
  try { deep = JSON.parse(r.deep_json || '[]'); } catch (e) { deep = []; }
  let reasons = [];
  try { reasons = JSON.parse(r.reasons || '[]'); } catch (e) { reasons = []; }

  // 双评级头：结构风险（五雷区） + 综合筛查（五雷区+深度取严）
  let html = `<div class="risk-head">
    <div class="rh-duo">
      <div class="rh-item risk-${zoneCls}">
        <div class="rh-item-label">结构风险</div>
        <div class="rh-item-val">${esc(zone)}</div>
      </div>
      <div class="rh-item risk-${compCls}">
        <div class="rh-item-label">综合筛查</div>
        <div class="rh-item-val">${esc(comp)}</div>
      </div>
    </div>
    <div class="rh-text">
      <div class="rh-title">暴雷检查</div>
      <div class="rh-sub">结构风险 = 五雷区硬信号（审计 / 利润结构 / 现金流 / 商誉 / 业绩拐点）；综合筛查 = 五雷区 + 深度检查取严${r.as_of ? ` · 数据截止 ${fmtDate(r.as_of)}` : ''}</div>
    </div>
  </div>`;

  // 触发项汇总
  if (reasons.length) {
    html += `<div class="callout callout-warn">${reasons.map(x => '· ' + esc(x)).join('<br>')}</div>`;
  } else {
    html += `<div class="callout callout-good">✅ 五雷区及深度检查均未触发预警</div>`;
  }

  // 五雷区矩阵
  html += `<table class="blk-table risk-table"><thead><tr><th>雷区</th><th>判定</th><th>说明</th></tr></thead><tbody>`;
  for (const [k, label, dk] of RISK_ZONES) {
    html += `<tr><td class="risk-zone">${label}</td><td>${riskLight(r[k])}</td><td class="risk-detail">${esc(r[dk] || '—')}</td></tr>`;
  }
  html += `</tbody></table>`;

  // 深度检查（默认折叠）
  if (deep.length) {
    const cnt = { '红': 0, '黄': 0, '绿': 0 };
    deep.forEach(c => { if (cnt[c.level] != null) cnt[c.level]++; });
    const summary = [cnt['红'] ? `红 ${cnt['红']}` : '', cnt['黄'] ? `黄 ${cnt['黄']}` : '', cnt['绿'] ? `绿 ${cnt['绿']}` : ''].filter(Boolean).join(' · ');
    html += `<details class="risk-deep"><summary>🔬 深度检查 ${deep.length} 项（${esc(summary)}）</summary>
      <table class="blk-table"><tbody>`;
    for (const c of deep) {
      html += `<tr><td class="risk-zone">${esc(c.name || '')}</td><td>${riskLight(c.level)}</td><td class="risk-detail">${esc(c.detail || '')}</td></tr>`;
    }
    html += `</tbody></table></details>`;
  }

  if (r.checked_at) html += `<p class="risk-foot">🤖 自动排雷（stock-analytics baolei）· 数据源 tushare · 检查于 ${esc(r.checked_at)}</p>`;
  return html;
}

/* ---------- 红绿灯（规则矩阵 + 最新值） ---------- */
const LIGHT_EMOJI = { green: '🟢', yellow: '🟡', red: '🔴' };
const LIGHT_LABEL = { green: '绿灯', yellow: '黄灯', red: '红灯' };
function lightBadge(r) {
  if (!r.current_light || !LIGHT_EMOJI[r.current_light]) return '';
  return `<span class="badge light-${esc(r.current_light)}">${LIGHT_EMOJI[r.current_light]} ${LIGHT_LABEL[r.current_light]}</span>`;
}
function renderTracking(d) {
  const rules = d.rules || [];
  const data = d.data || [];
  let html = '';
  if (rules.length) {
    html += `<table class="blk-table"><thead><tr><th>跟踪指标</th><th>当前</th><th>🟢 绿灯</th><th>🟡 黄灯</th><th>🔴 红灯</th></tr></thead><tbody>`;
    html += rules.map(r => `<tr><td><b>${esc(r.indicator || r.dimension || '—')}</b>${r.current_note ? `<div class="light-note">${esc(r.current_note)}</div>` : ''}</td>
      <td>${lightBadge(r) || '<span class="dim">未标注</span>'}</td>
      <td class="g">${esc(r.green || '—')}</td><td class="y">${esc(r.yellow || '—')}</td><td class="r">${esc(r.red || '—')}</td></tr>`).join('');
    html += '</tbody></table>';
  } else {
    html += '<p class="empty-sm">跟踪规则未配置（阈值待补充）</p>';
  }
  html += '<h3 class="sub-h">📋 最新值</h3>';
  if (data.length) {
    const shown = HEAD_DIMS.filter(k => data.find(t => t.dimension === k));
    html += `<table class="blk-table"><thead><tr><th>指标</th><th>最新值</th><th>日期</th></tr></thead><tbody>`;
    for (const dim of shown) {
      const t = data.find(x => x.dimension === dim);
      const meta = DIM_META[dim] || { label: dim, fmt: v => esc(v) };
      html += `<tr><td>${meta.label}</td><td><b>${meta.fmt(t.value)}</b></td><td>${fmtDate(t.as_of)}</td></tr>`;
    }
    html += '</tbody></table>';
  } else {
    html += '<p class="empty-sm">暂无跟踪数据</p>';
  }
  return html;
}

function renderCatalysts(d) {
  const cs = d.catalysts || [];
  if (!cs.length) return '<p class="empty-sm">暂无催化节点数据</p>';
  const stLabel = { pending: '待兑现', done: '已兑现', skipped: '跳过' };
  return `<div class="catalyst-list">${cs.map(c => `
    <div class="catalyst-row">
      <div class="cat-main"><b>${esc(c.name)}</b>
        <span class="badge cat-st-${esc(c.status || 'pending')}">${stLabel[c.status] || esc(c.status)}</span></div>
      <div class="cat-date">${esc(c.due_date || '')}</div>
      ${c.note ? `<p class="cat-note">${esc(c.note)}</p>` : ''}
    </div>`).join('')}</div>`;
}

function renderDividend(d) {
  const td = (d.data || []).find(x => x.dimension === 'dv_ratio');
  const pe = (d.data || []).find(x => x.dimension === 'pe_ttm');
  return `<div class="div-cards">
    <div class="card-static"><div class="cs-label">近12月股息率</div><div class="cs-val green">${td ? num(td.value, 2) + '%' : '—'}</div><div class="cs-sub">${td ? fmtDate(td.as_of) : ''}</div></div>
    <div class="card-static"><div class="cs-label">PE(TTM)</div><div class="cs-val">${pe ? num(pe.value, 1) : '—'}</div></div>
  </div>`;
}

/* ---------- 主流程 ---------- */
async function load() {
  const r = await fetch('/api/stocks-detail?code=' + encodeURIComponent(CODE));
  if (r.status === 404) { location.href = '/'; return; }
  const d = await r.json();
  if (!d.ok) { location.href = '/'; return; }
  const s = d.stock;
  document.title = s.name + ' · Stocks 研究站';
  const tpl = TEMPLATES[s.category] || DEFAULT_TPL;
  let html = renderHead(s, d.data);
  for (const id of tpl) {
    let body = '';
    if (id === 'pe') body = peChartSVG(d.pe, (() => { try { const a = JSON.parse(s.ttm_buy_range || '[]'); return a.length === 2 ? a : null; } catch (e) { return null; } })());
    else if (id === 'lines') body = renderLines(d);
    else if (id === 'modules') { const ms = renderModules(d); if (ms) html += ms; continue; }
    else if (id === 'poscheck') body = renderPosCheck(d);
    else if (id === 'tracking') body = renderTracking(d);
    else if (id === 'catalysts') body = renderCatalysts(d);
    else if (id === 'dividend') body = renderDividend(d);
    else if (id === 'discipline') body = renderDiscipline(d);
    else if (id === 'valuation') body = renderValuation(d);
    else if (id === 'risk') body = renderRisk(d);
    if (body == null) continue;
    html += `<section class="dsec"><h2>${TITLES[id]}</h2>${body}</section>`;
  }
  document.getElementById('detail').innerHTML = html;
}

document.getElementById('logout-btn').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  location.href = '/login';
});

(async () => {
  const u = await me();
  if (!u) return;
  await load();
})();