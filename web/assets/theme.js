/* 主题切换：默认浅色，可切深色，localStorage 记忆 */
(function () {
  const KEY = 'stocks-theme';
  function apply(theme) {
    document.body.classList.toggle('dark', theme === 'dark');
    const btn = document.getElementById('theme-btn');
    if (btn) btn.textContent = theme === 'dark' ? '☀️ 浅色' : '🌙 深色';
  }
  function initTheme() {
    let theme = localStorage.getItem(KEY) || 'light';
    apply(theme);
    const btn = document.getElementById('theme-btn');
    if (btn) btn.addEventListener('click', () => {
      const next = document.body.classList.contains('dark') ? 'light' : 'dark';
      localStorage.setItem(KEY, next);
      apply(next);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initTheme);
  else initTheme();
})();
