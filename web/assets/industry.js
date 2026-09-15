/* 产业详情：核心逻辑 + 产业跟踪红绿灯 + 成分股 */
const IND_ID = decodeURIComponent(location.pathname.slice('/industry/'.length));
const STAGE_LABEL = { boom: '爆发', grow: '成长', seed: '萌芽', mature: '成熟', decline: '衰退' };
const POS_LABEL = { leader: '龙头', core: '核心', minor: '次要', satellite: '卫星', optional: '期权' };
const WEIGHT_LABEL = { primary: '主', secondary: '次', tertiary: '三级', optional: '期权' };
const LINECAT_LABEL = {
  mainline: '🏭主脉线', frontier: '🔮卡位线', swing: '⚡短线线',
  dividend: '💎分红线', sunset: '🌇夕阳线', explosion: '🔥爆发线'
};

function esc(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
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

function renderInd(industry, members) {
  const tags = (() => { try { return JSON.parse(industry.tags || '[]'); } catch (e) { return []; } })();
  const rules = (() => { try { return JSON.parse(industry.track_indicators || '[]'); } catch (e) { return []; } })();
  let html = `<div class="detail-head">
    <div class="dh-top"><h1>🏭 ${esc(industry.name)} <span class="code">${esc(industry.id)}</span></h1>
      <span class="badge stage-${esc(industry.stage)}">${STAGE_LABEL[industry.stage] || esc(industry.stage)}</span></div>
    <div class="dh-tags">${tags.map(t => `<span class="badge">${esc(t)}</span>`).join('')}</div>
    <p class="dh-desc">${esc(industry.summary || '')}</p>
  </div>`;

  html += `<section class="dsec"><h2>🧭 核心逻辑</h2><p class="blk-text">${esc(industry.summary || '')}</p></section>`;

  html += `<section class="dsec"><h2>🚦 产业跟踪红绿灯</h2>`;
  if (rules.length) {
    html += `<table class="blk-table"><thead><tr><th>跟踪指标</th><th>🟢 绿灯</th><th>🟡 黄灯</th><th>🔴 红灯</th></tr></thead><tbody>`;
    html += rules.map(r => `<tr><td><b>${esc(r.indicator || '—')}</b></td>
      <td class="g">${esc(r.green || '—')}</td><td class="y">${esc(r.yellow || '—')}</td><td class="r">${esc(r.red || '—')}</td></tr>`).join('');
    html += '</tbody></table>';
  } else {
    html += '<p class="empty-sm">暂无产业红绿灯规则</p>';
  }
  html += '</section>';

  html += `<section class="dsec"><h2>📌 成分股（${members.length}）</h2>`;
  if (members.length) {
    html += `<div class="member-list">${members.map(m => `
      <a class="member-row" href="/stocks/${esc(m.code)}">
        <div class="mr-main"><b>${esc(m.name)}</b><span class="mr-code">${esc(m.code)}</span></div>
        <div class="mr-badges">
          ${m.position ? `<span class="badge pos-${esc(m.position)}">${POS_LABEL[m.position] || esc(m.position)}</span>` : ''}
          ${m.weight ? `<span class="badge">${WEIGHT_LABEL[m.weight] || esc(m.weight)}</span>` : ''}
          ${m.lineCat ? `<span class="badge lc">${LINECAT_LABEL[m.lineCat] || esc(m.lineCat)}</span>` : ''}
        </div>
        ${m.segment ? `<div class="mr-seg">${esc(m.segment)}</div>` : ''}
      </a>`).join('')}</div>`;
  } else {
    html += '<p class="empty-sm">暂无成分股</p>';
  }
  html += '</section>';
  return html;
}

async function load() {
  const r = await fetch('/api/industry/' + encodeURIComponent(IND_ID));
  if (r.status === 404) { location.href = '/industries'; return; }
  const d = await r.json();
  if (!d.ok) { location.href = '/industries'; return; }
  document.title = d.industry.name + ' · Stocks 研究站';
  document.getElementById('industry').innerHTML = renderInd(d.industry, d.members || []);
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