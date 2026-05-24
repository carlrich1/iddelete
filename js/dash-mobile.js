/* Mobile dashboard header behaviour — toggle menu, hydrate user initials.
   Loaded only on dashboard-style pages alongside app.js + api.js. */
(function () {
  function init() {
    const btn = document.querySelector('.dash-mobile-user');
    const menu = document.getElementById('dmm');
    if (!btn || !menu) return;

    // Toggle on tap, close when clicking anywhere else
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener('click', () => { menu.hidden = true; });
    menu.addEventListener('click', (e) => e.stopPropagation());

    // Hydrate user fields (poll briefly because page IIFE may not have run yet)
    let tries = 0;
    const t = setInterval(async () => {
      tries++;
      try {
        if (window.eyBackend) {
          await window.eyBackend.ready;
          const u = await window.eyBackend.me();
          if (u) {
            const name = (u.name || u.email || '').trim();
            const parts = name.split(/[\s@.]+/).filter(Boolean);
            const ii = ((parts[0] || '?')[0] + (parts[1] || '')[0]).toUpperCase().slice(0, 2);
            const $ = (id) => document.getElementById(id);
            if ($('dmu-initials')) $('dmu-initials').textContent = ii || '?';
            if ($('dmm-name')) $('dmm-name').textContent = u.name || '';
            if ($('dmm-email')) $('dmm-email').textContent = u.email || '';
            clearInterval(t);
          }
        }
      } catch (_) {}
      if (tries > 25) clearInterval(t);
    }, 200);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
