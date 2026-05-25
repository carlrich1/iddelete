/**
 * DarkTrace HIBP Proxy — Cloudflare Worker
 *
 * Proxies requests to HaveIBeenPwned API, keeping the API key server-side.
 * The HIBP_API_KEY is set via: npx wrangler secret put HIBP_API_KEY
 *
 * Endpoints:
 *   GET /breachedaccount/:email   → checks breaches for an email
 *   GET /pasteaccount/:email      → checks paste sites for an email
 *   GET /breaches                 → lists all known breaches
 *   GET /breach/:name             → details for a specific breach
 */

const HIBP_BASE = 'https://haveibeenpwned.com/api/v3';

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin') || '';

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: corsHeaders(origin, env),
      });
    }

    // Only GET allowed
    if (request.method !== 'GET') {
      return jsonResponse({ error: 'Method not allowed' }, 405, origin, env);
    }

    // Route the request
    const path = url.pathname;
    let upstream;

    if (path.startsWith('/breachedaccount/')) {
      const email = path.substring('/breachedaccount/'.length);
      if (!isValidEmail(decodeURIComponent(email))) {
        return jsonResponse({ error: 'Invalid email' }, 400, origin, env);
      }
      upstream = `${HIBP_BASE}/breachedaccount/${email}?truncateResponse=false`;
    } else if (path.startsWith('/pasteaccount/')) {
      const email = path.substring('/pasteaccount/'.length);
      if (!isValidEmail(decodeURIComponent(email))) {
        return jsonResponse({ error: 'Invalid email' }, 400, origin, env);
      }
      upstream = `${HIBP_BASE}/pasteaccount/${email}`;
    } else if (path === '/breaches') {
      upstream = `${HIBP_BASE}/breaches`;
    } else if (path.startsWith('/breach/')) {
      const name = path.substring('/breach/'.length);
      upstream = `${HIBP_BASE}/breach/${name}`;
    } else {
      return jsonResponse({ error: 'Not found' }, 404, origin, env);
    }

    // Forward to HIBP
    try {
      const hibpResponse = await fetch(upstream, {
        headers: {
          'hibp-api-key': env.HIBP_API_KEY,
          'User-Agent': 'DarkTrace-Scanner',
          'Accept': 'application/json',
        },
      });

      // 404 from HIBP means "no breaches found" — return empty array
      if (hibpResponse.status === 404) {
        return jsonResponse([], 200, origin, env);
      }

      // Pass through rate limit responses
      if (hibpResponse.status === 429) {
        const retryAfter = hibpResponse.headers.get('retry-after') || '6';
        return jsonResponse(
          { error: 'Rate limited', retryAfter },
          429,
          origin,
          env,
          { 'Retry-After': retryAfter }
        );
      }

      if (!hibpResponse.ok) {
        return jsonResponse(
          { error: `HIBP returned ${hibpResponse.status}` },
          hibpResponse.status,
          origin,
          env
        );
      }

      const data = await hibpResponse.json();
      return jsonResponse(data, 200, origin, env);
    } catch (err) {
      return jsonResponse({ error: 'Upstream fetch failed', detail: err.message }, 502, origin, env);
    }
  },
};

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function corsHeaders(origin, env) {
  // ALLOWED_ORIGIN can be:
  //   "*"                                   → allow any origin (dev only)
  //   "https://a.com"                       → allow exactly one origin
  //   "https://a.com,https://b.com,..."     → comma-separated allowlist
  const allowed = env.ALLOWED_ORIGIN || '*';
  let allowOrigin;
  if (allowed === '*') {
    allowOrigin = '*';
  } else {
    const allowList = allowed.split(',').map(s => s.trim()).filter(Boolean);
    allowOrigin = allowList.includes(origin) ? origin : allowList[0];
  }
  return {
    'Access-Control-Allow-Origin': allowOrigin,
    'Vary': 'Origin',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function jsonResponse(body, status, origin, env, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(origin, env),
      ...extraHeaders,
    },
  });
}
