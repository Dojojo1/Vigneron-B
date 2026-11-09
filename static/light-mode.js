(() => {
  'use strict';
  const key = 'heritage-light-mode';
  try {
    document.documentElement.classList.toggle('heritage-light-mode', localStorage.getItem(key) === '1');
  } catch { /* Private browsing may deny storage. */ }

  document.addEventListener('change', event => {
    if (event.target?.id !== 'light-mode-toggle') return;
    const enabled = event.target.checked;
    document.documentElement.classList.toggle('heritage-light-mode', enabled);
    try { localStorage.setItem(key, enabled ? '1' : '0'); } catch { /* Session-only setting. */ }
    document.dispatchEvent(new Event('heritage:light-mode'));
  });
})();
