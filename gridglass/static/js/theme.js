// Runs before the page paints so there is no flash of the wrong theme.
(function () {
  var saved = null;
  try { saved = localStorage.getItem('gg.theme'); } catch (e) { /* private mode */ }
  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  document.documentElement.dataset.theme = saved || (mq.matches ? 'dark' : 'light');
  // Follow the phone's setting until the user picks a theme themselves.
  mq.addEventListener('change', function (e) {
    var chosen = null;
    try { chosen = localStorage.getItem('gg.theme'); } catch (err) { /* ignore */ }
    if (!chosen) document.documentElement.dataset.theme = e.matches ? 'dark' : 'light';
  });
})();

// Moving between pages glides where the browser can (see "@view-transition" in app.css). If the glide is
// skipped — a quick second tap, or a page that can't take part — that's fine: don't report it as an error.
['pageswap', 'pagereveal'].forEach(function (name) {
  window.addEventListener(name, function (e) {
    var t = e.viewTransition;
    if (!t) return;
    [t.ready, t.finished].forEach(function (p) { if (p) p.catch(function () {}); });
  });
});
// Some browsers also reject a promise of their own when a page glide can't start; that isn't an error either.
window.addEventListener('unhandledrejection', function (e) {
  var message = e.reason && e.reason.message;
  if (e.reason && e.reason.name === 'AbortError' && /transition/i.test(message || '')) e.preventDefault();
  else if (/^Transition was (skipped|aborted)/.test(message || '')) e.preventDefault();
});
