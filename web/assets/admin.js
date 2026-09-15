/* 游客管理页（仅 admin） */
let users = [];

async function me() {
  try {
    const r = await fetch('/api/me');
    const d = await r.json();
    if (!d.authed) { location.href = '/login'; return null; }
    if (d.role !== 'admin') { location.href = '/'; return null; }
    document.getElementById('who').textContent = d.username + ' · 管理员';
    return d;
  } catch (e) { location.href = '/login'; return null; }
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

async function loadUsers() {
  const r = await fetch('/api/admin/users');
  if (r.status === 401) { location.href = '/login'; return; }
  if (r.status === 403) { location.href = '/'; return; }
  const d = await r.json();
  users = d.users || [];
  render();
}

function render() {
  const tb = document.querySelector('#user-table tbody');
  tb.innerHTML = '';
  for (const u of users) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${u.id}</td>
      <td><b>${esc(u.username)}</b></td>
      <td>${u.role === 'admin' ? '管理员' : '游客'}</td>
      <td class="${u.active ? 'tag-on' : 'tag-off'}">${u.active ? '启用' : '停用'}</td>
      <td>${esc((u.created_at || '').slice(0, 10))}</td>
      <td>
        ${u.role === 'admin' ? '<span style="color:var(--muted)">—</span>' : `
        <button class="ghost" data-act="reset" data-id="${u.id}">重置口令</button>
        <button class="ghost" data-act="toggle" data-id="${u.id}">${u.active ? '停用' : '启用'}</button>
        <button class="danger" data-act="del" data-id="${u.id}">删除</button>`}
      </td>`;
    tb.appendChild(tr);
  }
  tb.querySelectorAll('button[data-act]').forEach(btn => {
    btn.onclick = () => act(btn.dataset.act, btn.dataset.id);
  });
}

async function act(kind, id) {
  const u = users.find(x => String(x.id) === String(id));
  if (kind === 'reset') {
    const pass = prompt('为游客「' + (u ? u.username : '') + '」设置新口令（≥3位，口令即新身份）：');
    if (!pass) return;
    const r = await fetch('/api/admin/users/' + id + '/reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ passphrase: pass })
    });
    const d = await r.json();
    if (d.ok) alert('已重置，游客需用新口令重新登录');
    else alert(d.error || '失败');
  } else if (kind === 'toggle') {
    const r = await fetch('/api/admin/users/' + id + '/toggle', { method: 'POST' });
    const d = await r.json();
    if (!d.ok) alert(d.error || '失败');
  } else if (kind === 'del') {
    if (!confirm('确认删除游客「' + (u ? u.username : '') + '」？其会话将全部失效。')) return;
    const r = await fetch('/api/admin/users/' + id, { method: 'DELETE' });
    const d = await r.json();
    if (!d.ok) alert(d.error || '失败');
  }
  loadUsers();
}

/* 创建游客：只输口令 */
document.getElementById('create-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pass = document.getElementById('new-pass').value.trim();
  const msg = document.getElementById('create-msg');
  msg.textContent = '';
  msg.className = 'form-msg';
  const r = await fetch('/api/admin/users', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ passphrase: pass })
  });
  const d = await r.json();
  if (d.ok) {
    msg.textContent = '已创建游客，口令：' + pass;
    document.getElementById('new-pass').value = '';
    loadUsers();
  } else {
    msg.textContent = d.error || '创建失败';
    msg.className = 'form-msg err';
  }
});

/* 修改我的口令 */
const modal = document.getElementById('pass-modal');
const passMsg = document.getElementById('pass-msg');
document.getElementById('change-pass-btn').addEventListener('click', () => {
  document.getElementById('cur-pass').value = '';
  document.getElementById('my-new-pass').value = '';
  passMsg.textContent = '';
  modal.hidden = false;
  document.getElementById('cur-pass').focus();
});
document.getElementById('pass-cancel').addEventListener('click', () => { modal.hidden = true; });
document.getElementById('pass-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  passMsg.textContent = '';
  const r = await fetch('/api/me/password', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current: document.getElementById('cur-pass').value,
      next: document.getElementById('my-new-pass').value
    })
  });
  const d = await r.json();
  if (d.ok) {
    alert('口令已修改，请用新口令重新登录');
    location.href = '/login';
  } else {
    passMsg.textContent = d.error || '修改失败';
  }
});

document.getElementById('logout-btn').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  location.href = '/login';
});

(async () => {
  const u = await me();
  if (!u) return;
  await loadUsers();
})();