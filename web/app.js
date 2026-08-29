/* Shared bits for both FindMy Map pages. Loaded synchronously in <head> so
   the theme is applied before the first paint (no flash of the wrong theme). */

(function () {
  // Apply the saved theme as early as possible.
  try {
    var saved = localStorage.getItem('theme');
    if (saved === 'light' || saved === 'dark') {
      document.documentElement.dataset.theme = saved;
    }
  } catch (e) { /* private mode / storage disabled */ }

  function currentTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  }

  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch (e) {}
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      var toDark = theme === 'light';
      btn.textContent = toDark ? '☾' : '☀';   // ☾ when a click goes to dark, ☀ otherwise
      btn.title = toDark ? 'Dunkles Design' : 'Helles Design';
      btn.setAttribute('aria-label', btn.title);
    }
  }

  // Expose a hook so pages can react (e.g. redraw canvas layers) if needed.
  window.FindMyMap = window.FindMyMap || {};
  window.FindMyMap.onThemeChange = null;

  function toggle() {
    var next = currentTheme() === 'light' ? 'dark' : 'light';
    apply(next);
    if (typeof window.FindMyMap.onThemeChange === 'function') {
      window.FindMyMap.onThemeChange(next);
    }
  }

  window.FindMyMap.setupThemeToggle = function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    apply(currentTheme());
    btn.addEventListener('click', toggle);
  };

  // If the DOM is already parsed (script at end of body), wire it now;
  // otherwise wait. Pages also call setupThemeToggle() themselves after
  // building their header, which is idempotent enough for our needs.
  if (document.readyState !== 'loading') {
    window.FindMyMap.setupThemeToggle();
  } else {
    document.addEventListener('DOMContentLoaded', window.FindMyMap.setupThemeToggle);
  }
})();
