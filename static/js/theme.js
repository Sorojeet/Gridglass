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
