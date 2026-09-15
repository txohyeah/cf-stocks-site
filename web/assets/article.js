/* 文章详情：轻量 markdown 渲染 */
const SLUG = decodeURIComponent(location.pathname.slice('/article/'.length));

function esc(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

/* 极简 Markdown → HTML（标题/粗体/斜体/列表/表格/代码/引用/链接/段落） */
function md(origin) {
  const lines = origin.replace(/\r\n/g, '\n').split('\n');
  const out = [];
  let i = 0;
  let inTable = false;
  const flushTable = () => { if (inTable) { out.push('</table>'); inTable = false; } };
  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trim();
    if (!line) { flushTable(); out.push(''); i++; continue; }
    if (/^\|/.test(line)) {
      const cells = line.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      if (!inTable) {
        inTable = true;
        out.push('<table class="blk-table"><thead><tr>' + cells.map(c => '<th>' + inline(c) + '</th>').join('') + '</tr></thead><tbody>');
        i++;
        continue;
      }
      if (/^:?-{2,}:?$/.test(cells[0].replace(/-/g, '-'))) { i++; continue; } // 分隔行
      out.push('<tr>' + cells.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>');
      i++;
      continue;
    }
    flushTable();
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { out.push(`<h${h[1].length}>` + inline(h[2]) + `</h${h[1].length}>`); i++; continue; }
    if (/^(-{3,}|\*{3,})$/.test(line)) { out.push('<hr>'); i++; continue; }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(inline(lines[i].replace(/^>\s?/, ''))); i++; }
      out.push('<blockquote>' + buf.join('<br>') + '</blockquote>');
      continue;
    }
    if (/^\s*[-*+]\s+/.test(raw)) {
      const buf = ['<ul>'];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) { buf.push('<li>' + inline(lines[i].replace(/^\s*[-*+]\s+/, '')) + '</li>'); i++; }
      buf.push('</ul>');
      out.push(buf.join(''));
      continue;
    }
    if (/^\s*\d+\.\s+/.test(raw)) {
      const buf = ['<ol>'];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { buf.push('<li>' + inline(lines[i].replace(/^\s*\d+\.\s+/, '')) + '</li>'); i++; }
      buf.push('</ol>');
      out.push(buf.join(''));
      continue;
    }
    if (/^```/.test(line)) {
      const buf = ['<pre><code>'];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(esc(lines[i])); i++; }
      i++;
      buf.push('</code></pre>');
      out.push(buf.join('\n'));
      continue;
    }
    out.push('<p>' + inline(line) + '</p>');
    i++;
  }
  flushTable();
  return out.join('\n');
}

function inline(s) {
  let t = esc(s);
  // 行内代码
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  // 粗体+斜体 **x** / *x*（避免与链接冲突，先粗后斜）
  t = t.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
  // 链接 [text](url)
  t = t.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return t;
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
  const r = await fetch('/api/articles/' + encodeURIComponent(SLUG));
  if (r.status === 404) { location.href = '/articles'; return; }
  const d = await r.json();
  if (!d.ok) { location.href = '/articles'; return; }
  const a = d.article;
  document.title = a.title + ' · Stocks 研究站';
  const el = document.getElementById('article');
  el.innerHTML = '<h1>' + esc(a.title) + '</h1>' +
    (a.summary ? '<p class="ar-summary">' + esc(a.summary) + '</p>' : '') +
    '<div class="ar-meta">' + esc((a.updated_at || '').slice(0, 10)) + '</div>' +
    md(a.content_md || '');
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