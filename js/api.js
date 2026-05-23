/* ============================================
   ID Delete — backend bridge
   Talks to the Flask API when available; falls back to localStorage so
   the static site keeps working without a server.
   Exposes window.eyBackend and a window.eyBackend.ready promise.
   ============================================ */

(function () {
  let mode = 'local';

  // Probe the API once on load. CORS-safe because we serve same-origin.
  const ready = (async () => {
    try {
      const r = await fetch('/api/health', { credentials: 'include' });
      if (r.ok) mode = 'api';
    } catch (_) {
      mode = 'local';
    }
    return mode;
  })();

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts,
    });
    let data = null;
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) {
      const err = new Error((data && data.error) || `http_${r.status}`);
      err.status = r.status; err.body = data;
      throw err;
    }
    return data;
  }

  window.eyBackend = {
    ready,
    get mode() { return mode; },

    // ---------- auth ----------
    async me() {
      if (mode === 'api') {
        const d = await api('/api/auth/me');
        return d.user;
      }
      return window.eyAuth.getUser();
    },

    async signup(payload) {
      // payload: {name, email, password, plan, city, state}
      if (mode === 'api') {
        const d = await api('/api/auth/signup', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        return d.user;
      }
      // local fallback (mock-only mode)
      const user = {
        name: payload.name, email: payload.email,
        city: payload.city || '', state: payload.state || '',
        plan: payload.plan || 'family',
        joined: new Date().toISOString(),
      };
      window.eyAuth.setUser(user);
      localStorage.removeItem('iddelete_scan');
      return user;
    },

    async login(email, password) {
      if (mode === 'api') {
        const d = await api('/api/auth/login', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        });
        return d.user;
      }
      // local fallback: any creds work, create a placeholder if needed
      let user = window.eyAuth.getUser();
      if (!user || user.email !== email) {
        user = {
          name: email.split('@')[0].replace(/[._]/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
          email, plan: 'family', joined: new Date().toISOString(),
        };
        window.eyAuth.setUser(user);
        localStorage.removeItem('iddelete_scan');
      }
      return user;
    },

    async logout() {
      if (mode === 'api') {
        try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) {}
      }
      window.eyAuth.clear();
    },

    // ---------- scan ----------
    async getScan() {
      if (mode === 'api') {
        const d = await api('/api/scan');
        return d.exposures || [];
      }
      return window.eyGetScan();
    },

    async runScan() {
      if (mode === 'api') {
        await api('/api/scan/run', { method: 'POST' });
        return true;
      }
      // local: advance some statuses to simulate progress
      const scan = window.eyGetScan().map(s => {
        if (s.status === 'found' && Math.random() > 0.5) return { ...s, status: 'req', requestedAt: new Date().toISOString().slice(0, 10) };
        if (s.status === 'req'   && Math.random() > 0.6) return { ...s, status: 'gone', removedAt: new Date().toISOString().slice(0, 10) };
        return s;
      });
      window.eySaveScan(scan);
      return true;
    },

    async getRemovals() {
      if (mode === 'api') {
        const d = await api('/api/removals');
        return d.removals || [];
      }
      // local: same shape as scan, filter happens in the page
      return window.eyGetScan();
    },

    // ---------- profile ----------
    async updateProfile(payload) {
      if (mode === 'api') {
        await api('/api/profile', { method: 'PATCH', body: JSON.stringify(payload) });
      } else {
        const u = window.eyAuth.getUser() || {};
        Object.assign(u, payload);
        window.eyAuth.setUser(u);
      }
    },

    async deleteAccount() {
      if (mode === 'api') {
        try { await api('/api/account', { method: 'DELETE' }); } catch (_) {}
      }
      window.eyAuth.clear();
    },

    // ---------- billing ----------
    async billingConfig() {
      if (mode === 'api') {
        try { return await api('/api/billing/config'); } catch (_) { return { configured: false }; }
      }
      return { configured: false };
    },

    async startCheckout(plan) {
      if (mode !== 'api') return { error: 'api_required' };
      const base = location.origin;
      const d = await api('/api/billing/checkout', {
        method: 'POST',
        body: JSON.stringify({ plan, base_url: base }),
      });
      if (d.url) location.href = d.url;
      return d;
    },
  };
})();
