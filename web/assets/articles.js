/* 文章列表 */
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
  const r = await fetch('/api/articles');
  const d = await r.json();
  if (!d.ok) { location.href = '/login'; return; }
  const list = document.getElementById('article-list');
  const arts = d.articles || [];
  if (!arts.length) {
    list.innerHTML = '<p class="empty-sm">暂无文章</p>';
    return;
  }
  list.innerHTML = arts.map(a => `
    <a class="article-row" href="/article/${encodeURIComponent(a.slug)}">
      <div class="ar-title">${esc(a.title)}</div>
      ${a.summary ? `<div class="ar-summary">${esc(a.summary)}</div>` : ''}
      <div class="ar-meta">${(a.tags || '').split(',').filter(Boolean).length ? esc(a.tags) : ''} · ${esc((a.updated_at || '').slice(0, 10))}</div>
    </a>`).join('');
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