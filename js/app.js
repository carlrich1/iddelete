/* ============================================
   ID Delete — shared client logic
   Mock auth + dashboard data via localStorage.
   In production this would talk to a real API.
   ============================================ */

(function () {
  const STORAGE_KEY = 'iddelete_user';
  const SCAN_KEY    = 'iddelete_scan';

  // ---- Auth helpers ----
  window.eyAuth = {
    getUser() {
      try { return JSON.parse(localStorage.getItem(STORAGE_KEY)); }
      catch { return null; }
    },
    setUser(u) { localStorage.setItem(STORAGE_KEY, JSON.stringify(u)); },
    clear()    { localStorage.removeItem(STORAGE_KEY); localStorage.removeItem(SCAN_KEY); },
    requireAuth(redirect = 'login.html') {
      if (!this.getUser()) { window.location.href = redirect; return false; }
      return true;
    }
  };

  // ---- Data broker catalogue (sample of the 200+ we "cover") ----
  window.eyBrokers = [
    'Spokeo','WhitePages','BeenVerified','Intelius','PeopleFinder','Radaris',
    'TruthFinder','MyLife','PeopleLooker','InstantCheckmate','PublicRecordsNow',
    'FastPeopleSearch','USSearch','PeekYou','ClassMates','Acxiom','LexisNexis',
    'Epsilon','Oracle Data Cloud','Experian Marketing','PeopleSmart','ZabaSearch',
    'PrivateEye','Pipl','SearchPeopleFREE','BackgroundReport360','InfoTracer',
    'PeopleByName','USPhoneBook','BlockShopper','CourtCaseFinder','Nuwber',
    'CheckPeople','SearchQuarry','411.info','AnyWho','PeopleConnect',
    'FamilyTreeNow','ThatsThem','AdvancedBackgroundChecks','Cubib','Yasni',
    'PublicData','OpenCorporates','Veripages','Wink','MyHeritage','Archives',
    'FindPeopleSearch','PublicRecordsReviews','LocatePeople','SmartBackgroundChecks'
  ];

  // ---- Generate a deterministic mock scan from a name ----
  window.eyMockScan = function (name, email) {
    // Pick ~22-32 brokers from list with statuses
    const brokers = window.eyBrokers;
    const seed = (name || 'user').toLowerCase().split('').reduce((a,c)=>a + c.charCodeAt(0), 0);
    const rand = (n) => {
      // simple LCG
      let x = seed + n*9301 + 49297;
      return (x % 233280) / 233280;
    };
    const count = 22 + Math.floor(rand(1) * 10);
    const picked = [];
    for (let i = 0; i < count; i++) {
      picked.push(brokers[(seed + i*7) % brokers.length]);
    }
    const unique = [...new Set(picked)];
    const states = ['found', 'req', 'gone'];
    return unique.map((b, i) => {
      const r = rand(i + 5);
      // Distribution: 55% found, 30% requested, 15% removed at start
      const s = r < 0.55 ? 'found' : r < 0.85 ? 'req' : 'gone';
      const exposed = [];
      if (rand(i+10) > .2) exposed.push('Full name');
      if (rand(i+11) > .3) exposed.push('Home address');
      if (rand(i+12) > .5) exposed.push('Phone number');
      if (rand(i+13) > .6) exposed.push('Email');
      if (rand(i+14) > .75) exposed.push('Date of birth');
      if (rand(i+15) > .85) exposed.push('Relatives');
      return {
        broker: b,
        status: s,
        exposed,
        requestedAt: s !== 'found' ? `2026-04-${String(10 + (i%18)).padStart(2,'0')}` : null,
        removedAt:  s === 'gone' ? `2026-05-${String(2 + (i%14)).padStart(2,'0')}` : null,
      };
    });
  };

  window.eyGetScan = function () {
    let scan;
    try { scan = JSON.parse(localStorage.getItem(SCAN_KEY)); } catch {}
    if (scan) return scan;
    const u = window.eyAuth.getUser();
    if (!u) return [];
    scan = window.eyMockScan(u.name || u.email, u.email);
    localStorage.setItem(SCAN_KEY, JSON.stringify(scan));
    return scan;
  };

  window.eySaveScan = function (scan) {
    localStorage.setItem(SCAN_KEY, JSON.stringify(scan));
  };

  // ---- Mobile nav toggle ----
  document.addEventListener('DOMContentLoaded', () => {
    const t = document.querySelector('.menu-toggle');
    const n = document.querySelector('.nav');
    if (t && n) t.addEventListener('click', () => n.classList.toggle('open'));

    // Hide login/signup if already logged in; show dashboard link instead
    const u = window.eyAuth.getUser();
    const loginBtn  = document.querySelector('[data-when="loggedout"]');
    const dashBtn   = document.querySelector('[data-when="loggedin"]');
    if (u) {
      if (loginBtn) loginBtn.style.display = 'none';
      if (dashBtn)  dashBtn.style.display = '';
    } else {
      if (dashBtn) dashBtn.style.display = 'none';
    }

    // Logout buttons (use eyBackend.logout if loaded for API-aware logout)
    document.querySelectorAll('[data-action="logout"]').forEach(b => {
      b.addEventListener('click', async (e) => {
        e.preventDefault();
        if (window.eyBackend && window.eyBackend.logout) {
          try { await window.eyBackend.logout(); } catch (_) {}
        } else {
          window.eyAuth.clear();
        }
        window.location.href = 'index.html';
      });
    });
  });
})();
