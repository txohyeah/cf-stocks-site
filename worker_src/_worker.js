// stocks 站点 — 全站口令门禁 + D1 数据网关
// 权限模型：无匿名。未登录访问任何页面 → 302 跳 /login；API 未登录 → 401。
//   游客(guest)：管理员创建的口令身份，登录后可看全部内容
//   管理员(admin)：唯一内置，可在 /admin.html 维护游客（增删/重置口令/启停）
// 口令哈希：PBKDF2-SHA256，存 pbkdf2$iter$salt_b64$hash_b64
// 会话：token 存 D1 sessions 表，HttpOnly Cookie，30 天
const COOKIE = 'stocks_auth';
const SESSION_DAYS = 30;
const PBKDF2_ITER = 100000;
const PBKDF2_KEYLEN = 32;

// ---------- utils ----------
const enc = new TextEncoder();
function b64FromBytes(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}
function bytesFromB64(s) {
  const bin = atob(s);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
function json(data, status) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }
  });
}
function nowIso() { return new Date().toISOString(); }
function addDays(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
}
function clean(s) { return (s || '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }

// ---------- passphrase ----------
async function deriveBytes(passphrase, saltB64, iter, keylen) {
  const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(passphrase), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: bytesFromB64(saltB64), iterations: iter },
    keyMaterial, keylen * 8);
  return new Uint8Array(bits);
}
async function hashPass(passphrase) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const bits = await deriveBytes(passphrase, b64FromBytes(salt), PBKDF2_ITER, PBKDF2_KEYLEN);
  return 'pbkdf2$' + PBKDF2_ITER + '$' + b64FromBytes(salt) + '$' + b64FromBytes(bits);
}
async function verifyPass(passphrase, stored) {
  try {
    const parts = (stored || '').split('$');
    if (parts.length !== 4 || parts[0] !== 'pbkdf2') return false;
    const iter = parseInt(parts[1], 10);
    const bits = await deriveBytes(passphrase, parts[2], iter, PBKDF2_KEYLEN);
    const expect = bytesFromB64(parts[3]);
    if (bits.length !== expect.length) return false;
    let diff = 0;
    for (let i = 0; i < bits.length; i++) diff |= bits[i] ^ expect[i];
    return diff === 0;
  } catch (e) { return false; }
}

// ---------- session ----------
function cookieToken(request) {
  const cookie = request.headers.get('Cookie') || '';
  const m = cookie.match(new RegExp('(?:^|;\\s*)' + COOKIE + '=([^;]+)'));
  return m ? m[1] : null;
}
async function currentUser(request, env) {
  const token = cookieToken(request);
  if (!token) return null;
  const row = await env.DB.prepare(
    `SELECT s.token, s.expires_at, u.id AS user_id, u.username, u.role, u.active
     FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?`
  ).bind(token).first();
  if (!row) return null;
  if (row.expires_at < nowIso() || !row.active) {
    await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
    return null;
  }
  return { token, userId: row.user_id, username: row.username, role: row.role };
}
function cookieFor(token) {
  return `${COOKIE}=${token}; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=${SESSION_DAYS * 86400}`;
}
function clearCookieFor() {
  return `${COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=0`;
}
async function serveStatic(urlstr, env) {
  const r = await env.ASSETS.fetch(urlstr);
  const h = new Headers(r.headers);
  h.set('Cache-Control', 'no-store');
  return new Response(r.body, { status: r.status, headers: h });
}

// ---------- API handlers ----------
async function issueSession(user, env) {
  const token = crypto.randomUUID();
  const exp = addDays(SESSION_DAYS);
  await env.DB.prepare('INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)')
    .bind(token, user.id, exp, nowIso()).run();
  return new Response(JSON.stringify({ ok: true, username: user.username, role: user.role }), {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Set-Cookie': cookieFor(token)
    }
  });
}
async function apiLogin(request, env) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const username = (body.username || '').trim();
  const passphrase = body.passphrase || '';
  if (!passphrase) return json({ error: '请输入口令' }, 400);
  if (!username) {
    // 游客：只有口令（身份=口令），遍历启用的游客逐个比对
    const guests = (await env.DB.prepare("SELECT * FROM users WHERE role = 'guest' AND active = 1").all()).results;
    for (const g of guests) {
      if (await verifyPass(passphrase, g.passphrase_hash)) return issueSession(g, env);
    }
    return json({ error: '口令错误' }, 401);
  }
  // 管理员/具名用户：用户名 + 口令
  const user = await env.DB.prepare('SELECT * FROM users WHERE username = ? AND active = 1').bind(username).first();
  if (!user) return json({ error: '用户名或口令错误' }, 401);
  const ok = await verifyPass(passphrase, user.passphrase_hash);
  if (!ok) return json({ error: '用户名或口令错误' }, 401);
  return issueSession(user, env);
}
async function apiLogout(request, env) {
  const token = cookieToken(request);
  if (token) await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'Set-Cookie': clearCookieFor() }
  });
}
async function apiMe(request, env) {
  const u = await currentUser(request, env);
  if (!u) return json({ authed: false }, 200);
  return json({ authed: true, username: u.username, role: u.role });
}
async function apiStocks(request, env) {
  const url = new URL(request.url);
  const category = url.searchParams.get('category') || '';
  const lineCat = url.searchParams.get('lineCat') || '';
  const industry = url.searchParams.get('industry') || '';
  const recent = url.searchParams.get('recent') === '1';
  const q = (url.searchParams.get('q') || '').trim();
  let sql = `SELECT s.code, s.name, s.sector, s.category, s.subtype, s.tags, s.desc, s.pe_current, s.pe_date, s.ttm_buy_range, s.buy_range_type, s.added_at
             FROM stocks s WHERE s.tracked = 1`;
  const params = [];
  if (category) { sql += ' AND s.category = ?'; params.push(category); }
  if (lineCat) { sql += ' AND EXISTS (SELECT 1 FROM industry_lines x WHERE x.stock_code = s.code AND x.lineCat = ?)'; params.push(lineCat); }
  if (industry) { sql += ' AND EXISTS (SELECT 1 FROM industry_lines x WHERE x.stock_code = s.code AND x.line_id = ?)'; params.push(industry); }
  if (recent) {
    // 最近 24h 添加（东八区），added_at 为 'YYYY-MM-DD HH:MM:SS'（历史纯日期回填为当天 00:00:00）
    const cutoff = fmtLocal(new Date(Date.now() - 86400000));
    sql += ' AND s.added_at >= ?'; params.push(cutoff);
  }
  if (q) {
    sql += ' AND (s.name LIKE ? OR s.code LIKE ? OR s.tags LIKE ? OR s.desc LIKE ? OR s.subtype LIKE ?)';
    const like = '%' + q + '%';
    params.push(like, like, like, like, like);
  }
  sql += ' ORDER BY s.category, s.name';
  const { results } = await env.DB.prepare(sql).bind(...params).all();
  const lines = (await env.DB.prepare(
    'SELECT stock_code, lineCat, line_id FROM industry_lines').all()).results;
  const byCode = {};
  for (const l of lines) (byCode[l.stock_code] = byCode[l.stock_code] || []).push({ lineCat: l.lineCat, line_id: l.line_id });
  for (const s of results) s.lines = byCode[s.code] || [];
  return json({ ok: true, total: results.length, stocks: results });
}

// 东八区时间格式化 'YYYY-MM-DD HH:MM:SS'
function fmtLocal(d) {
  const off = 8 * 3600 * 1000; // UTC+8
  return new Date(d.getTime() + off).toISOString().slice(0, 19).replace('T', ' ');
}
async function apiIndustries(env) {
  const { results } = await env.DB.prepare(
    'SELECT id, name, stage, summary, segments, tags, track_indicators FROM industries ORDER BY stage, name').all();
  return json({ ok: true, total: results.length, industries: results });
}
async function apiIndustry(env, id) {
  const ind = await env.DB.prepare(
    'SELECT id, name, stage, summary, segments, tags, track_indicators FROM industries WHERE id = ?').bind(id).first();
  if (!ind) return json({ error: '产业不存在' }, 404);
  const members = (await env.DB.prepare(
    'SELECT il.stock_code AS code, s.name, il.position, il.weight, il.lineCat, il.segment ' +
    'FROM industry_lines il JOIN stocks s ON s.code = il.stock_code ' +
    'WHERE il.line_id = ? ORDER BY s.name').bind(id).all()).results;
  return json({ ok: true, industry: ind, members });
}
async function apiArticles(env) {
  const { results } = await env.DB.prepare(
    'SELECT id, slug, title, summary, tags, updated_at FROM articles WHERE published = 1 ORDER BY updated_at DESC').all();
  return json({ ok: true, total: results.length, articles: results });
}

// ---------- admin: 仅 admin，仅游客维护 ----------
async function requireAdmin(request, env) {
  const u = await currentUser(request, env);
  if (!u) return { error: json({ error: '未登录' }, 401) };
  if (u.role !== 'admin') return { error: json({ error: '无权限' }, 403) };
  return { user: u };
}
async function adminListUsers(request, env) {
  const { results } = await env.DB.prepare(
    'SELECT id, username, role, active, created_at FROM users ORDER BY role DESC, id').all();
  return json({ ok: true, users: results });
}
async function adminCreateUser(request, env) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const passphrase = (body.passphrase || '').trim();   // 游客身份 = 口令本身
  if (!passphrase) return json({ error: '登录口令必填' }, 400);
  if (passphrase.length < 3) return json({ error: '口令至少 3 位' }, 400);
  const exists = await env.DB.prepare('SELECT id FROM users WHERE username = ?').bind(passphrase).first();
  if (exists) return json({ error: '该口令已存在，换一个' }, 409);
  const hash = await hashPass(passphrase);
  const ts = nowIso();
  const res = await env.DB.prepare(
    'INSERT INTO users (username, passphrase_hash, role, active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)')
    .bind(passphrase, hash, 'guest', ts, ts).run();
  return json({ ok: true, id: res.meta.last_row_id, username: passphrase });
}
async function adminResetPass(request, env, id) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const passphrase = (body.passphrase || '').trim();
  if (!passphrase || passphrase.length < 3) return json({ error: '口令至少 3 位' }, 400);
  const exists = await env.DB.prepare('SELECT id FROM users WHERE username = ? AND id != ?').bind(passphrase, id).first();
  if (exists) return json({ error: '该口令已被其他用户使用' }, 409);
  const hash = await hashPass(passphrase);
  await env.DB.prepare('UPDATE users SET username = ?, passphrase_hash = ?, updated_at = ? WHERE id = ?')
    .bind(passphrase, hash, nowIso(), id).run();
  await env.DB.prepare('DELETE FROM sessions WHERE user_id = ?').bind(id).run();
  return json({ ok: true });
}
async function changeMyPassword(request, env, u) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const current = body.current || '';
  const next = (body.next || '').trim();
  if (!next || next.length < 3) return json({ error: '新口令至少 3 位' }, 400);
  const user = await env.DB.prepare('SELECT * FROM users WHERE id = ?').bind(u.userId).first();
  if (!user) return json({ error: '用户不存在' }, 404);
  const ok = await verifyPass(current, user.passphrase_hash);
  if (!ok) return json({ error: '当前口令错误' }, 400);
  const hash = await hashPass(next);
  await env.DB.prepare('UPDATE users SET passphrase_hash = ?, updated_at = ? WHERE id = ?')
    .bind(hash, nowIso(), u.userId).run();
  // 游客身份=口令，改名同步（admin 不动）
  if (user.role === 'guest') {
    await env.DB.prepare('UPDATE users SET username = ? WHERE id = ?').bind(next, u.userId).run();
  }
  // 强制所有会话失效（含当前），前端提示重新登录
  await env.DB.prepare('DELETE FROM sessions WHERE user_id = ?').bind(u.userId).run();
  return json({ ok: true });
}
async function adminToggleUser(request, env, id) {
  const u = await env.DB.prepare('SELECT id, role FROM users WHERE id = ?').bind(id).first();
  if (!u) return json({ error: '用户不存在' }, 404);
  if (u.role === 'admin') return json({ error: '不能停用 admin' }, 400);
  await env.DB.prepare('UPDATE users SET active = 1 - active, updated_at = ? WHERE id = ?').bind(nowIso(), id).run();
  return json({ ok: true });
}
async function adminDeleteUser(request, env, id) {
  const u = await env.DB.prepare('SELECT id, role FROM users WHERE id = ?').bind(id).first();
  if (!u) return json({ error: '用户不存在' }, 404);
  if (u.role === 'admin') return json({ error: '不能删除 admin' }, 400);
  await env.DB.prepare('DELETE FROM sessions WHERE user_id = ?').bind(id).run();
  await env.DB.prepare('DELETE FROM users WHERE id = ?').bind(id).run();
  return json({ ok: true });
}

// ---------- main fetch ----------
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    const method = request.method;

    // 健康检查
    if (p === '/api/health') return json({ ok: true, t: nowIso() });

    // 登录（唯一无需会话的 API）
    if (p === '/api/login' && method === 'POST') return apiLogin(request, env);

    // /api/* 一律需要会话
    if (p.startsWith('/api/')) {
      const u = await currentUser(request, env);
      if (!u) return json({ error: '未登录' }, 401);
      if (p === '/api/logout' && method === 'POST') return apiLogout(request, env);
      if (p === '/api/me') return apiMe(request, env);
      if (p === '/api/me/password' && method === 'POST') return changeMyPassword(request, env, u);
      if (p === '/api/stocks' && method === 'GET') return apiStocks(request, env);
      if (p === '/api/stocks-detail') {
        const code = url.searchParams.get('code') || '';
        if (!code) return json({ error: '缺 code' }, 400);
        const stock = await env.DB.prepare(
          'SELECT code, name, sector, category, subtype, tags, desc, pe_current, pe_date, ttm_buy_range, buy_range_type FROM stocks WHERE code = ?'
        ).bind(code).first();
        if (!stock) return json({ error: '不存在' }, 404);
        const lines = (await env.DB.prepare(
          'SELECT il.line_id, il.position, il.weight, il.lineCat, il.segment, il.note, i.name AS line_name, i.stage AS line_stage ' +
          'FROM industry_lines il LEFT JOIN industries i ON i.id = il.line_id ' +
          'WHERE il.stock_code = ? ORDER BY il.sort_order, il.id').bind(code).all()).results;
        const modules = (await env.DB.prepare(
          'SELECT m.id, m.module_key, m.title, m.template_key, m.sort_order FROM stock_modules m WHERE m.stock_code = ? AND m.visible = 1 ORDER BY m.sort_order, m.id').bind(code).all()).results;
        const moduleIds = modules.map(m => m.id);
        const blocks = moduleIds.length ? (await env.DB.prepare(
          `SELECT module_id, block_type, data_json, sort_order FROM module_blocks WHERE module_id IN (${moduleIds.map(() => '?').join(',')}) ORDER BY module_id, sort_order, id`
        ).bind(...moduleIds).all()).results : [];
        const blocksByModule = {};
        for (const b of blocks) {
          (blocksByModule[b.module_id] = blocksByModule[b.module_id] || []).push({
            type: b.block_type, data: JSON.parse(b.data_json || '{}'), sort_order: b.sort_order
          });
        }
        const rules = (await env.DB.prepare(
          'SELECT dimension, indicator, red, yellow, green, current_light, current_note FROM tracking_rules WHERE stock_code = ? ORDER BY sort_order, id').bind(code).all()).results;
        const data = (await env.DB.prepare(
          'SELECT dimension, value, as_of FROM tracking_data WHERE stock_code = ? ORDER BY id').bind(code).all()).results;
        const catalysts = (await env.DB.prepare(
          'SELECT name, due_date, status, note FROM catalysts WHERE stock_code = ? ORDER BY sort_order, id').bind(code).all()).results;
        const pe = (await env.DB.prepare(
          'SELECT trade_date, pe_ttm FROM pe_history WHERE stock_code = ? ORDER BY trade_date').bind(code).all()).results;
        // 暴雷检查（表可能尚未建立 → 容错为 null，不影响详情页其他数据）
        let risk = null;
        try {
          risk = await env.DB.prepare(
            'SELECT rating, rating_zone, r0, r0_detail, r1, r1_detail, r2, r2_detail, r3, r3_detail, r4, r4_detail, ' +
            'deep_json, reasons, as_of, checked_at FROM risk_checks WHERE stock_code = ?').bind(code).first();
        } catch (e) { risk = null; }
        return json({ ok: true, stock, lines, modules: modules.map(m => ({ ...m, blocks: blocksByModule[m.id] || [] })), rules, data, catalysts, pe, risk: risk || null });
      }
      if (p === '/api/industries' && method === 'GET') return apiIndustries(env);
      const am_ind = p.match(/^\/api\/industry\/([^\/]+)$/);
      if (am_ind && method === 'GET') return apiIndustry(env, decodeURIComponent(am_ind[1]));
      if (p === '/api/articles' && method === 'GET') return apiArticles(env);
      const am_art = p.match(/^\/api\/articles\/(.+)$/);
      if (am_art && method === 'GET') {
        const slug = am_art[1];
        const a = await env.DB.prepare('SELECT * FROM articles WHERE slug = ? AND published = 1').bind(slug).first();
        return a ? json({ ok: true, article: a }) : json({ error: '不存在' }, 404);
      }

      // admin API
      const am = p.match(/^\/api\/admin\/users(?:\/(\d+))?(?:\/(\w+))?$/);
      if (am) {
        const guard = await requireAdmin(request, env);
        if (guard.error) return guard.error;
        const id = am[1] ? parseInt(am[1], 10) : null;
        const action = am[2] || '';
        if (method === 'GET' && !id) return adminListUsers(request, env);
        if (method === 'POST' && !id) return adminCreateUser(request, env);
        if (method === 'POST' && id && action === 'reset') return adminResetPass(request, env, id);
        if (method === 'POST' && id && action === 'toggle') return adminToggleUser(request, env, id);
        if (method === 'DELETE' && id) return adminDeleteUser(request, env, id);
        return json({ error: '不支持的操作' }, 400);
      }
      return json({ error: '未找到' }, 404);
    }

    // 白名单静态：登录页 + 资源 + 小图标
    if (p === '/login' || p === '/login.html') return serveStatic(url.origin + '/login.html', env);
    if (p === '/assets/' || p.startsWith('/assets/')) return serveStatic(url.origin + p, env);
    if (p === '/favicon.ico') return serveStatic(url.origin + '/favicon.ico', env);
    if (p === '/robots.txt') return serveStatic(url.origin + '/robots.txt', env);

    // 其余所有页面：必须登录，未登录 302 → /login
    const u = await currentUser(request, env);
    if (!u) {
      return new Response(null, {
        status: 302,
        headers: { Location: '/login', 'Cache-Control': 'no-store' }
      });
    }
    // admin 页面仅 admin
    if (p.startsWith('/admin') && u.role !== 'admin') {
      return json({ error: '无权限' }, 403);
    }
    // 详情页：/stocks/<code>，标的必须存在
    if (p.startsWith('/stocks/')) {
      const code = decodeURIComponent(p.slice('/stocks/'.length));
      const st = await env.DB.prepare('SELECT code FROM stocks WHERE code = ? AND tracked = 1').bind(code).first();
      if (!st) {
        return new Response(null, { status: 302, headers: { Location: '/', 'Cache-Control': 'no-store' } });
      }
      return serveStatic(url.origin + '/detail.html', env);
    }
    // 产业地图/产业详情/文章页/聪明钱报告
    const pageMap = { '/industries': '/industries.html', '/articles': '/articles.html', '/smart-money': '/smart-money.html' };
    const industryPage = p.match(/^\/industry\/([^\/]+)$/);
    if (industryPage) {
      const ind = await env.DB.prepare('SELECT id FROM industries WHERE id = ?').bind(decodeURIComponent(industryPage[1])).first();
      if (!ind) return json({ error: '产业不存在' }, 404);
      return serveStatic(url.origin + '/industry.html', env);
    }
    const articlePage = p.match(/^\/article\/([^\/]+)$/);
    if (articlePage) {
      const a = await env.DB.prepare('SELECT slug FROM articles WHERE slug = ? AND published = 1').bind(decodeURIComponent(articlePage[1])).first();
      if (!a) return json({ error: '文章不存在' }, 404);
      return serveStatic(url.origin + '/article.html', env);
    }
    const target = p === '/'
      ? '/index.html'
      : (p === '/admin' ? '/admin.html' : (pageMap[p] || p));
    return serveStatic(url.origin + target, env);
  }
};