/* 宏观环境页（/macro）
   一次 /api/macro 取数 → 本期体检 / 预期差时间轴 / 月度趋势 / 资金面 / 未来日程
   数据由 scripts/sync_macro.py 灌入 D1，源为 tushare（经 stock-analytics 落库） */
const C_MAIN = '#4c9aff', C_ALT = '#d29922', C_UP = '#3fb950', C_DOWN = '#f85149', C_GRID = '#2e3a49', C_MUTED = '#8b98a9';

function esc(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}
function num(v, d) {
  if (v == null || isNaN(v)) return '—';
  const s = Number(v).toFixed(d == null ? 1 : d);
  return s.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
}
/* 发布值/预期/预期差统一换算成"元"级，便于跨单位比较与画图。
   注意：value_num/fore_num/surprise 在 stock-analytics 落库时**已归一成绝对量**
   （如 1,660.0B 存 1.66e12），unit 只用于展示与文案，这里**不能**再乘一次量级。 */
function toYuan(v) { return v == null ? null : Number(v); }
function fmtYuan(v) {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e12) return num(v / 1e12, 2) + ' 万亿';
  if (a >= 1e8) return num(v / 1e8, 0) + ' 亿';
  return num(v, 0);
}
function dateCn(d) { return d ? d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6, 8) : '—'; }
function monthCn(m) { return m ? (/^\d{4}Q\d$/.test(m) ? m.slice(0, 4) + ' ' + m.slice(4) : m.slice(0, 4) + '-' + m.slice(4, 6)) : '—'; }
function weekCn(d) {
  if (!d) return '';
  const t = new Date(d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6, 8) + 'T00:00:00+08:00');
  return '周' + '日一二三四五六'[t.getDay()];
}
/* 发布事件名去掉月份后缀，只留指标名 */
function baseName(event) {
  return String(event || '').replace(/\((一|二|三|四|五|六|七|八|九|十|十一|十二)月\)/g, '').trim();
}

async function me() {
  try {
    const d = await (await fetch('/api/me')).json();
    if (!d.authed) { location.href = '/login'; return null; }
    document.getElementById('who').textContent = d.username;
    return d;
  } catch (e) { location.href = '/login'; return null; }
}

/* ---------- 通用图元 ---------- */
function gridLines(y, y0, y1, W, PAD, fmt) {
  let g = '';
  for (let i = 0; i <= 4; i++) {
    const v = y0 + (y1 - y0) * i / 4, yy = y(v);
    g += `<line x1="${PAD}" y1="${yy.toFixed(1)}" x2="${W - 12}" y2="${yy.toFixed(1)}" stroke="${C_GRID}" stroke-width="1"/>` +
      `<text x="${PAD - 6}" y="${(yy + 4).toFixed(1)}" fill="${C_MUTED}" font-size="11" text-anchor="end">${fmt(v)}</text>`;
  }
  return g;
}
function xLabels(pts, x, W, PAD, H, fmt) {
  const idxs = [0, Math.floor((pts.length - 1) / 2), pts.length - 1];
  return idxs.filter((v, i) => idxs.indexOf(v) === i).map(i =>
    `<text x="${x(i).toFixed(1)}" y="${H - 6}" fill="${C_MUTED}" font-size="11" text-anchor="${i === 0 ? 'start' : (i === pts.length - 1 ? 'end' : 'middle')}">${fmt(pts[i].x)}</text>`
  ).join('');
}
/* 折线图：pts = [{x:'2026-08', y:12.3}] */
function lineSVG(pts, o) {
  o = o || {};
  if (!pts || pts.length < 2) return '<p class="empty-sm">数据不足</p>';
  const W = 700, H = o.H || 210, PAD = 48, TOP = 14;
  const vals = pts.map(p => p.y);
  let y0 = Math.min.apply(null, vals), y1 = Math.max.apply(null, vals);
  if (o.zero) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  const buf = ((y1 - y0) * 0.15) || 1;
  y0 -= buf; y1 += buf;
  const x = i => PAD + i * (W - PAD - 14) / (pts.length - 1);
  const y = v => H - 20 - (v - y0) / (y1 - y0) * (H - 20 - TOP);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p.y).toFixed(1)).join(' ');
  const last = pts[pts.length - 1];
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    ${gridLines(y, y0, y1, W, PAD, o.yfmt || (v => num(v, 1)))}
    ${o.zero ? `<line x1="${PAD}" y1="${y(0).toFixed(1)}" x2="${W - 12}" y2="${y(0).toFixed(1)}" stroke="${C_MUTED}" stroke-width="1" stroke-dasharray="4 3"/>` : ''}
    <path d="${d}" fill="none" stroke="${o.color || C_MAIN}" stroke-width="2.2" stroke-linejoin="round"/>
    <circle cx="${x(pts.length - 1).toFixed(1)}" cy="${y(last.y).toFixed(1)}" r="3.6" fill="${o.dot || '#79b8ff'}"/>
    ${xLabels(pts, x, W, PAD, H, o.xfmt || (v => v))}
  </svg>`;
}
/* 多序列折线（CPI vs PPI） */
function multiLineSVG(pts, series, o) {
  o = o || {};
  if (!pts || pts.length < 2) return '<p class="empty-sm">数据不足</p>';
  const W = 700, H = o.H || 210, PAD = 48, TOP = 14;
  const all = [];
  for (const s of series) for (const v of s.values) if (v != null) all.push(v);
  if (!all.length) return '<p class="empty-sm">数据不足</p>';
  let y0 = Math.min.apply(null, all), y1 = Math.max.apply(null, all);
  if (o.zero) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  const buf = ((y1 - y0) * 0.15) || 1;
  y0 -= buf; y1 += buf;
  const x = i => PAD + i * (W - PAD - 14) / (pts.length - 1);
  const y = v => H - 20 - (v - y0) / (y1 - y0) * (H - 20 - TOP);
  let paths = '';
  for (const s of series) {
    const seg = s.values.map((v, i) => v == null ? null : [i, v]).filter(Boolean);
    if (!seg.length) continue;
    paths += `<path d="${seg.map((p, i) => (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[1]).toFixed(1)).join(' ')}" fill="none" stroke="${s.color}" stroke-width="2.2" stroke-linejoin="round"/>`;
    const l = seg[seg.length - 1];
    paths += `<circle cx="${x(l[0]).toFixed(1)}" cy="${y(l[1]).toFixed(1)}" r="3.2" fill="${s.color}"/>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    ${gridLines(y, y0, y1, W, PAD, o.yfmt || (v => num(v, 1)))}
    ${o.zero ? `<line x1="${PAD}" y1="${y(0).toFixed(1)}" x2="${W - 12}" y2="${y(0).toFixed(1)}" stroke="${C_MUTED}" stroke-width="1" stroke-dasharray="4 3"/>` : ''}
    ${paths}${xLabels(pts, x, W, PAD, H, o.xfmt || (v => v))}</svg>`;
}
/* 柱状图（可正负） */
function barSVG(pts, o) {
  o = o || {};
  if (!pts || !pts.length) return '<p class="empty-sm">数据不足</p>';
  const W = 700, H = o.H || 200, PAD = 48, TOP = 14;
  const vals = pts.map(p => p.y).filter(v => v != null);
  if (!vals.length) return '<p class="empty-sm">数据不足</p>';
  let y0 = Math.min(0, Math.min.apply(null, vals)), y1 = Math.max(0, Math.max.apply(null, vals));
  const buf = ((y1 - y0) * 0.12) || 1;
  y0 -= buf; y1 += buf;
  const bw = (W - PAD - 14) / pts.length;
  const x = i => PAD + i * bw;
  const y = v => H - 20 - (v - y0) / (y1 - y0) * (H - 20 - TOP);
  let bars = '';
  pts.forEach((p, i) => {
    if (p.y == null) return;
    const yv = y(p.y), yz = y(0);
    const top = Math.min(yv, yz), h = Math.max(1.5, Math.abs(yv - yz));
    bars += `<rect x="${(x(i) + bw * 0.18).toFixed(1)}" y="${top.toFixed(1)}" width="${(bw * 0.64).toFixed(1)}" height="${h.toFixed(1)}" fill="${p.y >= 0 ? (o.color || C_MAIN) : (o.negColor || C_DOWN)}" rx="1.5"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    ${gridLines(y, y0, y1, W, PAD, o.yfmt || (v => num(v, 1)))}
    ${bars}${xLabels(pts, x, W, PAD, H, o.xfmt || (v => v))}</svg>`;
}

/* ---------- 本期体检 ---------- */
const RECENT_DAYS = 60;
function daysAgo(d, today) {
  const a = new Date(d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6, 8) + 'T00:00:00+08:00');
  const b = new Date(today.slice(0, 4) + '-' + today.slice(4, 6) + '-' + today.slice(6, 8) + 'T00:00:00+08:00');
  return Math.round((b - a) / 86400000);
}
function kpiCard(title, valHtml, sub) {
  return `<div class="mc-kpi"><div class="k-name">${esc(title)}</div><div class="k-val">${valHtml}</div><div class="k-sub">${sub}</div></div>`;
}
function renderCheckup(d) {
  const today = d.today, out = [];
  const items = Object.keys(d.latest).map(k => Object.assign({ key: k }, d.latest[k]))
    .filter(x => daysAgo(x.date, today) <= RECENT_DAYS)
    .sort((a, b) => b.date.localeCompare(a.date));
  for (const x of items) {
    const yuan = toYuan(x.value_num), fore = toYuan(x.fore_num);
    let valHtml, sub;
    if (x.unit === '%' || x.unit === '') {
      valHtml = esc(x.value || '—');
      if (x.fore_value) {
        const dv = (x.value_num != null && x.fore_num != null) ? x.value_num - x.fore_num : null;
        sub = `预期 ${esc(x.fore_value)}` + (dv == null ? '' : ` ｜ <span class="${dv > 0 ? 'mc-up' : (dv < 0 ? 'mc-down' : 'mc-flat')}">${dv > 0 ? '+' : ''}${num(dv, 2)} 个百分点</span>`);
      } else sub = '无预期数据';
    } else {
      valHtml = fmtYuan(yuan);
      const dv = (yuan != null && fore != null) ? yuan - fore : null;
      sub = fore == null ? '无预期数据'
        : `预期 ${fmtYuan(fore)} ｜ <span class="${dv > 0 ? 'mc-up' : (dv < 0 ? 'mc-down' : 'mc-flat')}">${dv > 0 ? '+' : ''}${fmtYuan(dv)}</span>`;
    }
    out.push(kpiCard(`${x.key} · ${dateCn(x.date).slice(5)}`, valHtml, sub));
  }
  return out.length ? `<div class="mc-kpi-grid">${out.join('')}</div>`
    : '<p class="empty-sm">近 60 天没有已公布的核心指标</p>';
}
/* 货币三项（月度序列最新一期）+ 资金面三项（日频最新值） */
function renderMoney(d) {
  const ser = d.series || [], dly = d.daily || [];
  const lastOf = name => { const a = ser.filter(x => x.indicator === name); return a.length ? a[a.length - 1] : null; };
  const m1 = lastOf('M1同比'), m2 = lastOf('M2同比'), sc = lastOf('M1M2剪刀差');
  const dl = name => { const a = dly.filter(x => x.indicator === name); return a.length ? a[a.length - 1] : null; };
  const cards = [];
  const pctCard = (t, r) => cards.push(kpiCard(t, r ? num(r.value, 1) + '%' : '—', r ? `${monthCn(r.month)} 公布` : '无数据'));
  pctCard('M1 同比', m1); pctCard('M2 同比', m2);
  if (sc) cards.push(kpiCard('M1-M2 剪刀差', `${num(sc.value, 1)} <span class="muted" style="font-size:12px">百分点</span>`,
    `${monthCn(sc.month)} ｜ <span class="${sc.value > 0 ? 'mc-up' : 'mc-down'}">${sc.value > 0 ? '资金活化（M1 强于 M2）' : '资金淤积（M2 强于 M1）'}</span>`));
  const sh = dl('Shibor隔夜');
  cards.push(kpiCard('Shibor 隔夜', sh ? num(sh.value, 2) + '%' : '—', sh ? `${dateCn(sh.trade_date)}` : '无数据'));
  const mg = dly.filter(x => x.indicator === '两融余额');
  if (mg.length) {
    const last = mg[mg.length - 1], prev = mg.length > 21 ? mg[mg.length - 21] : mg[0];
    const chg = last.value - prev.value, chgPct = chg / prev.value * 100;
    cards.push(kpiCard('两融余额', num(last.value / 1e4, 2) + ' <span class="muted" style="font-size:12px">万亿</span>',
      `${dateCn(last.trade_date)} ｜ 近 20 日 <span class="${chg >= 0 ? 'mc-up' : 'mc-down'}">${chg >= 0 ? '+' : ''}${num(chgPct, 1)}%</span>`));
  }
  const nm = dly.filter(x => x.indicator === '北向净买');
  if (nm.length) {
    const win = nm.slice(-20);
    const sum = win.reduce((a, b) => a + (b.value || 0), 0);
    cards.push(kpiCard('北向 20 日累计', fmtYuan(sum * 1e8),
      `截至 ${dateCn(win[win.length - 1].trade_date)} ｜ 20 日区间`));
  }
  return `<div class="mc-kpi-grid">${cards.join('')}</div>
    <p class="mc-note">M1/M2/剪刀差取 <b>tushare 月度序列（cn_m）最新一期</b>；同月"当期发布值 + 市场预期"看上方本期体检。
      资金面取日频数据，北向为 20 日滚动累计。</p>`;
}

/* ---------- 🧭 框架条件变量体检（文章《产业投资框架》第 1 节定义） ---------- */
const COND_ICON = { ok: '✅', warn: '⏳', bad: '❌', gap: '⛔' };
function renderFramework(d) {
  const rows = d.conditions || [];
  const dly = d.daily || [];
  const pick = name => dly.filter(x => x.indicator === name).slice(-250)
    .map(x => ({ x: dateCn(x.trade_date), y: x.value }));
  const charts = [
    ['布伦特原油（美元/桶）', pick('布伦特原油'), { color: C_ALT, dot: C_ALT, dec: 2 }],
    ['美债 10Y（%）', pick('美债10Y'), { color: '#79b8ff', dot: '#79b8ff', dec: 2 }],
    ['离岸人民币 USDCNH', pick('离岸人民币'), { color: C_UP, dot: C_UP, dec: 4 }],
  ].map(([title, pts, opt]) => {
    const lastY = pts.length ? pts[pts.length - 1].y : null;
    return `<div class="mc-chart"><h4>${title}</h4>${lineSVG(pts, opt)}
      <p class="mc-legend">最新 ${lastY == null ? '—' : num(lastY, opt.dec)} ｜ 近 ${pts.length} 个交易日</p></div>`;
  }).join('');

  const body = rows.map(r => {
    const icon = COND_ICON[r.status_kind] || '⏳';
    return `<tr>
      <td class="cond-name"><b>${esc(r.title)}</b><div class="cond-target">${esc(r.target_text)}</div></td>
      <td>${esc(r.current_text)}${r.note ? `<div class="cond-note">${esc(r.note)}</div>` : ''}</td>
      <td class="cond-status k-${esc(r.status_kind)}">${icon} ${esc(r.status_text)}
        <div class="cond-src">${r.source_kind === 'manual' ? '手工' : '自动'} ｜ ${esc(r.source)}</div></td>
    </tr>`;
  }).join('');
  const updated = rows.length && rows[0].updated_at ? rows[0].updated_at.slice(0, 16) : '—';
  return `<table class="mc-table mc-cond"><thead><tr><th>条件</th><th>当前实测</th><th>状态</th></tr></thead>
    <tbody>${body}</tbody></table>
    <div class="mc-grid" style="margin-top:14px">${charts}</div>
    <p class="mc-note">条件变量取自文章 <a href="/article/investment-framework">《产业投资框架 · 从宏观到个股的完整方法论》</a> 第 1 节——
      每条都在回答<b>"什么情况下这个框架的判断是错的"</b>。<b>自动</b>项由 D1 每日刷新（tushare：美债/汇率；新浪外盘：布伦特/WTI）；
      <b>手工</b>项来自公开新闻（库内无数据源，录入在 scripts/macro_manual.json）。本轮更新：${esc(updated)}。</p>`;
}

/* ---------- 预期差时间轴（零轴居中条） ---------- */
function renderSurprise(d) {
  const rows = d.surprises || [];
  if (!rows.length) return '<p class="empty-sm">暂无已公布的社融/信贷数据</p>';
  const diffs = rows.map(r => toYuan(r.surprise)).filter(v => v != null);
  const mx = Math.max(1, Math.max.apply(null, diffs.map(Math.abs)));
  const body = rows.map(r => {
    const yuan = toYuan(r.value_num), fore = toYuan(r.fore_num), dv = toYuan(r.surprise);
    const w = Math.abs(dv || 0) / mx * 50;              // 半幅 = 50%
    const left = dv >= 0 ? 50 : 50 - w;
    const tag = /新增人民币贷款|信贷/.test(r.event) ? '信贷' : '社融';
    const tagMonth = (r.event.match(/\((一|二|三|四|五|六|七|八|九|十|十一|十二)月\)/) || [])[1] || '';
    return `<div class="sr-row">
      <span class="sr-label">${dateCn(r.date).slice(5)} ${tag}${tagMonth ? '·' + tagMonth + '月' : ''}</span>
      <span class="sr-bar"><svg viewBox="0 0 100 16" preserveAspectRatio="none">
        <rect x="49.7" y="0" width="0.6" height="16" fill="${C_MUTED}"/>
        <rect x="${left.toFixed(1)}" y="3" width="${Math.max(0.8, w).toFixed(1)}" height="10" fill="${dv >= 0 ? C_UP : C_DOWN}" rx="1"/>
      </svg></span>
      <span class="sr-val">实际 <b>${fmtYuan(yuan)}</b> ／ 预期 ${fore == null ? '—' : fmtYuan(fore)}
        <span class="${dv >= 0 ? 'mc-up' : 'mc-down'}">（${dv >= 0 ? '+' : ''}${fmtYuan(dv)}）</span></span>
    </div>`;
  }).join('');
  return `<div class="sr-list">${body}</div>
    <p class="mc-note">柱子方向 = 实际减预期：<span class="mc-up">向右（绿）为超预期</span>、<span class="mc-down">向左（红）为不及预期</span>。
      社融/信贷是按月发布的<b>单月增量</b>（如 1,660.0B = 1.66 万亿），不是存量增速。</p>`;
}

/* ---------- 月度趋势 ---------- */
function seriesOf(ser, name, n) {
  const a = ser.filter(x => x.indicator === name).sort((a, b) => a.month.localeCompare(b.month));
  return a.slice(-(n || 36));
}
function renderTrend(d) {
  const ser = d.series || [];
  const sf = seriesOf(ser, '社融增量').map(x => ({ x: monthCn(x.month), y: x.value / 1e4 }));            // 亿元 → 万亿
  const cpi = seriesOf(ser, 'CPI同比'), ppi = seriesOf(ser, 'PPI同比');
  const months = cpi.map(x => x.month);
  const cpiPts = months.map((m, i) => ({ x: monthCn(m), y: cpi[i] ? cpi[i].value : null }));
  const ppiMap = {}; ppi.forEach(x => ppiMap[x.month] = x.value);
  const ppiVals = months.map(m => (m in ppiMap ? ppiMap[m] : null));
  const sc = seriesOf(ser, 'M1M2剪刀差').map(x => ({ x: monthCn(x.month), y: x.value }));
  const sfLast = sf.length ? sf[sf.length - 1] : null;
  const cpiLast = cpi.length ? cpi[cpi.length - 1] : null, ppiLast = ppi.length ? ppi[ppi.length - 1] : null;
  const scLast = sc.length ? sc[sc.length - 1] : null;
  return `<div class="mc-grid">
    <div class="mc-chart"><h4>社融增量（单月，万亿）</h4>
      ${barSVG(sf, { yfmt: v => num(v, 1), xfmt: v => v.slice(2) })}
      <p class="mc-legend">最新 ${sfLast ? sfLast.x + '：' + num(sfLast.y, 2) + ' 万亿' : '—'}；近 36 个月</p></div>
    <div class="mc-chart"><h4>CPI 与 PPI 同比（%）</h4>
      ${multiLineSVG(cpiPts, [{ values: cpiPts.map(p => p.y), color: C_MAIN }, { values: ppiVals, color: C_ALT }],
        { zero: true, yfmt: v => num(v, 1), xfmt: v => v.slice(2) })}
      <p class="mc-legend"><i style="background:${C_MAIN}"></i>CPI
        <i style="background:${C_ALT}"></i>PPI ｜ 最新
        CPI ${cpiLast ? num(cpiLast.value, 1) + '%' : '—'}、PPI ${ppiLast ? num(ppiLast.value, 1) + '%' : '—'}
        ${(cpiLast && ppiLast) ? `（PPI-CPI 剪刀差 ${num(ppiLast.value - cpiLast.value, 1)} 个百分点）` : ''}</p></div>
    <div class="mc-chart"><h4>M1-M2 剪刀差（百分点）</h4>
      ${barSVG(sc, { yfmt: v => num(v, 1), xfmt: v => v.slice(2) })}
      <p class="mc-legend">最新 ${scLast ? scLast.x + '：' + num(scLast.y, 1) + ' 百分点' : '—'}；
        负值 = M2 增长快于 M1（资金偏"淤积"）</p></div>
  </div>`;
}

/* ---------- 资金面 ---------- */
function renderFunding(d) {
  const dly = d.daily || [];
  const pick = name => dly.filter(x => x.indicator === name).slice(-250)
    .map(x => ({ x: dateCn(x.trade_date), y: x.value }));
  const sh = pick('Shibor隔夜');
  const mg = pick('两融余额').map(p => ({ x: p.x, y: p.y / 1e4 }));                     // 亿元 → 万亿
  const raw = dly.filter(x => x.indicator === '北向净买').slice(-250);
  const nm = [];                                                                        // 20 日滚动累计
  for (let i = 0; i < raw.length; i++) {
    if (i < 19) continue;
    let s = 0;
    for (let j = i - 19; j <= i; j++) s += raw[j].value || 0;
    nm.push({ x: dateCn(raw[i].trade_date), y: s });
  }
  const last = a => (a.length ? a[a.length - 1].y : null);
  return `<div class="mc-grid">
    <div class="mc-chart"><h4>Shibor 隔夜（%）</h4>${lineSVG(sh, { dot: '#79b8ff' })}
      <p class="mc-legend">最新 ${last(sh) == null ? '—' : num(last(sh), 2) + '%'} ｜ 近 ${sh.length} 个交易日</p></div>
    <div class="mc-chart"><h4>两融余额（万亿）</h4>${lineSVG(mg, { color: C_ALT, dot: C_ALT })}
      <p class="mc-legend">最新 ${last(mg) == null ? '—' : num(last(mg), 2) + ' 万亿'} ｜ 沪深两市合计（融资+融券余额）</p></div>
    <div class="mc-chart"><h4>北向资金 20 日滚动累计（亿元）</h4>${lineSVG(nm, { zero: true, color: C_MAIN, dot: '#79b8ff' })}
      <p class="mc-legend">最新 ${last(nm) == null ? '—' : num(last(nm), 0) + ' 亿'} ｜ 20 日净买入滚动求和（>0 = 净流入）</p></div>
  </div>`;
}

/* ---------- 未来日程 ---------- */
function renderUpcoming(d) {
  const up = d.upcoming || [];
  if (!up.length) return '<p class="empty-sm">未来 45 天内暂无已排期的发布</p>';
  return `<table class="mc-table"><thead><tr><th>日期</th><th>时间</th><th>事件</th></tr></thead><tbody>
    ${up.map(x => `<tr><td class="d">${dateCn(x.date)} ${weekCn(x.date)}</td><td class="d">${esc(x.time || '—')}</td><td>${esc(baseName(x.event))}</td></tr>`).join('')}
  </tbody></table>`;
}

async function load() {
  const r = await fetch('/api/macro');
  const d = await r.json();
  if (!d.ok) { location.href = '/login'; return; }
  const asOf = d.as_of || {};
  document.getElementById('mc-asof').textContent =
    `发布日历至 ${dateCn(asOf.cal)} ｜ 月度序列至 ${monthCn(asOf.ser)} ｜ 日频至 ${dateCn(asOf.dly)}`;
  document.getElementById('mc-body').innerHTML = `
    <div class="mc-panel mc-panel-cond"><h3>🧭 框架条件变量体检 <span class="muted" style="font-size:12px">这篇文章说"什么情况下我错了"——这里每天对一次账</span></h3>
      ${renderFramework(d)}</div>
    <div class="mc-panel"><h3>本期体检 <span class="muted" style="font-size:12px">近 60 天已公布的核心指标（实际 vs 市场预期）</span></h3>
      ${renderCheckup(d)}</div>
    <div class="mc-panel"><h3>货币与资金面</h3>${renderMoney(d)}</div>
    <div class="mc-panel"><h3>预期差时间轴 <span class="muted" style="font-size:12px">最近 12 次社融 / 信贷发布</span></h3>
      ${renderSurprise(d)}</div>
    <div class="mc-panel"><h3>月度趋势 <span class="muted" style="font-size:12px">近 36 期</span></h3>${renderTrend(d)}</div>
    <div class="mc-panel"><h3>资金面 <span class="muted" style="font-size:12px">近 1 年</span></h3>${renderFunding(d)}</div>
    <div class="mc-panel"><h3>未来 45 天发布日程</h3>${renderUpcoming(d)}</div>
    <div class="mc-panel"><h3>说明</h3>
      <p class="mc-note">
        <b>数据源</b>：tushare（eco_cal 发布日历 / sf_month 社融 / cn_m 货币 / cn_cpi / cn_ppi / cn_gdp / shibor / margin 两融 / moneyflow_hsgt 北向 /
        us_tycr 美债收益率 / fx_daily 离岸人民币）+ <b>新浪财经全球期货日线</b>（布伦特、WTI —— tushare 侧无外盘原油权限，实测 index_global 只有股指、
        fut_basic(IPE/NYMEX) 为空），经 stock-analytics 落库后由 <b>scripts/sync_macro.py</b> 每日同步到本站 D1。<br>
        <b>口径</b>：社融、信贷为按月发布的<b>单月增量</b>（如 2026-08 社融 1,660.0B = 1.66 万亿），不是存量；"预期"为发布前市场一致预期，
        两者之差即"预期差"。预期差的<b>方向</b>只说明数据比预期强或弱，不构成对指数或个股方向的判断。<br>
        <b>前瞻</b>：发布日历含未来已排期事件（值为空），公布后自动补上实际值；未来日程按当前已排期展示，临时调整以交易所/统计局公告为准。<br>
        <b>定位</b>：本页只摆宏观数据，不产生买卖信号；判断一律回到"聪明钱"与个股产业定位。<br>
        <b>免责</b>：数据可能存在延迟、缺失或修正，仅供研究参考，不构成投资建议。
      </p></div>`;
}

(async function () { if (await me()) await load(); })();
