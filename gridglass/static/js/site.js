// Information pages: only the light/dark switch. (The app has its own copy in app.js.)
(function () {
  function label(theme) { return theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'; }
  function apply(theme, save) {
    document.documentElement.dataset.theme = theme;
    if (save) { try { localStorage.setItem('gg.theme', theme); } catch (e) { /* private mode */ } }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'dark' ? '#070B12' : '#EEF3F6');
    document.querySelectorAll('[data-action="theme"]').forEach(function (b) { b.setAttribute('aria-label', label(theme)); });
  }
  apply(document.documentElement.dataset.theme, false);
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-action="theme"]')) apply(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true);
  });
})();
