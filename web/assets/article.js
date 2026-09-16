/* 文章详情：轻量 markdown 渲染 */
const SLUG = decodeURIComponent(location.pathname.slice('/article/'.length));

function esc(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

/* 标题 → 锚点 id（固定 sec- 前缀，避免以数字开头导致 CSS 选择器不可用） */
function slugify(text, used) {
  const base = 'sec-' + (text.replace(/<[^>]*>/g, '').trim()
    .replace(/\s+/g, '-')
    .replace(/[^\w\u4e00-\u9fa5-]/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
    .toLowerCase() || 'item');
  let id = base;
  let n = 2;
  while (used.has(id)) { id = base + '-' + (n++); }
  used.add(id);
  return id;
}

/* 目录：h2 顶层 + h3 缩进一层（从正文标题自动生成，杜绝手写锚点失效） */
function tocHtml(toc) {
  const items = toc.filter(t => t.level === 2 || t.level === 3);
  if (items.length < 3) return '';
  return '<nav class="ar-toc"><div class="ar-toc-title">目录</div>' + items.map(t =>
    `<a class="ar-toc-lv${t.level}" href="#${t.id}">${t.text}</a>`).join('') + '</nav>';
}

/* 极简 Markdown → HTML（标题/粗体/斜体/列表/表格/代码/引用/链接/段落） */
function md(origin) {
  const lines = origin.replace(/\r\n/g, '\n').split('\n');
  const out = [];
  const toc = [];
  const used = new Set();
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
    if (h) {
      const lv = h[1].length;
      const id = slugify(h[2], used);
      toc.push({ level: lv, text: h[2].replace(/\*\*/g, ''), id });
      out.push(`<h${lv} id="${id}">` + inline(h[2]) + `</h${lv}>`);
      i++;
      continue;
    }
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
  return { html: out.join('\n'), toc };
}

function inline(s) {
  let t = esc(s);
  // 行内代码
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  // 粗体+斜体 **x** / *x*（避免与链接冲突，先粗后斜）
  t = t.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
  // 站内锚点 [text](#id)（目录/交叉引用）
  t = t.replace(/\[([^\]]+)\]\(#([^)]+)\)/g, '<a href="#$2">$1</a>');
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
  const { html, toc } = md(a.content_md || '');
  el.innerHTML = '<h1>' + esc(a.title) + '</h1>' +
    (a.summary ? '<p class="ar-summary">' + esc(a.summary) + '</p>' : '') +
    '<div class="ar-meta">' + esc((a.updated_at || '').slice(0, 10)) + '</div>' +
    tocHtml(toc) + '<div class="ar-body">' + html + '</div>';
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