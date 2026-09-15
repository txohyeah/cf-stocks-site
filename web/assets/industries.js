/* 产业地图：48 产业 ÷ 5 阶段分组卡片 */
const STAGE_ORDER = ['boom', 'grow', 'seed', 'mature', 'decline'];
const STAGE_LABEL = { boom: '爆发', grow: '成长', seed: '萌芽', mature: '成熟', decline: '衰退' };
const POS_LABEL = { leader: '龙头', core: '核心', minor: '次要', satellite: '卫星', optional: '期权' };

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

async function load() {
  const r = await fetch('/api/industries');
  const d = await r.json();
  if (!d.ok) { location.href = '/login'; return; }
  const inds = d.industries || [];
  document.getElementById('ind-count').textContent = '共 ' + inds.length + ' 个产业';
  const groups = {};
  for (const x of inds) (groups[x.stage] = groups[x.stage] || []).push(x);
  const wrap = document.getElementById('ind-groups');
  let html = '';
  for (const stage of STAGE_ORDER) {
    const list = groups[stage] || [];
    if (!list.length) continue;
    html += `<div class="ind-stage-group"><h3 class="ind-stage-h ${stage}">${STAGE_LABEL[stage]} <span class="muted">${list.length} 个产业</span></h3>
      <div class="ind-card-grid">${list.map(x => `
        <a class="ind-card" href="/industry/${encodeURIComponent(x.id)}">
          <div class="ic-top"><b>${esc(x.name)}</b><span class="badge stage-${esc(x.stage)}">${STAGE_LABEL[x.stage] || esc(x.stage)}</span></div>
          <div class="ic-members">${esc(x.memberNames || '')}</div>
          <p class="ic-summary">${esc(x.summary || '')}</p>
        </a>`).join('')}</div></div>`;
  }
  wrap.innerHTML = html;

  // 拉成分股名（一次 API 太重，直接调 /api/industry 逐个太慢——用汇总接口）
  await enrichMembers(inds);
}

/* 逐个产业拿成分股（48 次 API 可接受，业界页面加载后异步填充） */
async function enrichMembers(inds) {
  for (const x of inds) {
    try {
      const r = await fetch('/api/industry/' + encodeURIComponent(x.id));
      const d = await r.json();
      if (!d.ok) continue;
      const members = d.members || [];
      if (!members.length) continue;
      const card = document.querySelector(`a.ind-card[href="/industry/${CSS.escape(x.id)}"] .ic-members`);
      if (card) card.textContent = members.map(m => m.name + '·' + (POS_LABEL[m.position] || m.position || '')).join('  ');
    } catch (e) { /* 忽略，保持空 */ }
  }
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