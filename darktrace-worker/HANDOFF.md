# DarkTrace — Handoff for Cowork

**Project**: DarkTrace dark web breach scanner
**Brand**: Sikuli Capital (separate sub-brand from the parent business)
**Origin**: First built April 15, 2026; verbatim rebuild May 24, 2026 for Cowork handoff
**Target domain**: `darktrace.sikulicapital.com`

## What this is

A consumer-grade dark web / breach exposure scanner positioned against incumbents like DeleteMe, LifeLock, and Aura in the $15B+ identity protection market. Brand differentiator: **radical transparency** — we don't pretend to remove data from the dark web (which is largely impossible). We tell the truth and automate the defensive actions that actually work.

This is the **scanning** piece of a planned four-capability suite:
1. **Dark web breach scanning** (this — DarkTrace, via HIBP API) ✓ built
2. Automated data broker opt-out submissions (Python/Playwright) — separate component, separate session
3. Credit freeze automation across Equifax/Experian/TransUnion (semi-automatable due to SMS 2FA)
4. Remediation guidance generation

## Architecture

Two-piece Cloudflare deployment:

```
[ Browser ] ──→ [ Cloudflare Pages: darktrace.sikulicapital.com ]
                                │
                                │  (fetch from frontend JS)
                                ▼
                [ Cloudflare Worker: darktrace-hibp-proxy ]
                                │
                                │  (with hibp-api-key header from secret)
                                ▼
                [ HaveIBeenPwned API v3 ]
```

The Worker exists for one reason: **keep the HIBP API key off the client**. The key is stored as an encrypted Wrangler secret (`HIBP_API_KEY`), never in code or the frontend.

## Files

### `darktrace-worker/` — Cloudflare Worker (the backend proxy)
- `src/index.js` — main Worker code; handles `/breachedaccount/:email`, `/pasteaccount/:email`, `/breaches`, `/breach/:name`; CORS handling; 404→empty-array translation; rate-limit pass-through
- `wrangler.toml` — config; `ALLOWED_ORIGIN` currently `"*"` for dev, should be locked to `https://darktrace.sikulicapital.com` before prod
- `package.json` — `wrangler dev`, `wrangler deploy`, `wrangler tail` scripts

### `darktrace-pages/` — Cloudflare Pages (the frontend)
- `index.html` — single-file frontend; Share Tech Mono + Rajdhani fonts; cyberpunk dark teal/cyan palette with magenta accent; animated grid background; parallel fetch of breaches + pastes; renders summary stats + breach cards

## Deployment steps

### Worker (do this first — Pages needs the Worker URL)

```bash
cd darktrace-worker
npm install
npx wrangler login          # one-time, opens browser for Cloudflare auth
npx wrangler secret put HIBP_API_KEY
# (paste the HIBP key when prompted — Carl has it; ask him)
npx wrangler deploy
```

Note the deployed URL — looks like `https://darktrace-hibp-proxy.<subdomain>.workers.dev`.

### Frontend

1. Open `darktrace-pages/index.html`
2. Find this line:
   ```js
   const WORKER_URL = 'https://darktrace-hibp-proxy.YOUR-SUBDOMAIN.workers.dev';
   ```
3. Replace with the actual Worker URL from the deploy step
4. Deploy to Cloudflare Pages:
   - Easiest: drag-and-drop the `darktrace-pages` folder into Cloudflare dashboard → Pages → Create project → Direct Upload
   - Or via Wrangler: `npx wrangler pages deploy darktrace-pages`
5. Bind custom domain `darktrace.sikulicapital.com` in the Pages project settings (Carl owns sikulicapital.com on Cloudflare already, so DNS will auto-configure)

### After Pages is live, lock down CORS

Edit `darktrace-worker/wrangler.toml`:
```toml
[vars]
ALLOWED_ORIGIN = "https://darktrace.sikulicapital.com"
```
Then `npx wrangler deploy` again.

## HIBP API key

Carl has the key. It's a paid HIBP subscription key (the breach/paste endpoints require it). Pricing is per-key per-month — confirm tier before launch.

## Next steps (planned but not built)

These were the items on the roadmap when the original April session ended:

1. **Cloudflare D1 backend** — add scan history per email and basic user accounts. This was the stated next priority. D1 binding in `wrangler.toml`, schema for `scans` table (email_hash, scanned_at, breach_count, paste_count, data_classes), API endpoints to list prior scans
2. **Email hashing before storage** — don't store plaintext emails in D1; hash them
3. **Rate limiting on the Worker** — currently relies on HIBP's own rate limits and will pass-through 429s, but should add per-IP throttling at the Worker layer before opening to the public
4. **Tier gating** — free scan returns top-level results only, paid tier returns full breach details + data classes
5. **Stripe integration** for the consumer SaaS ($10–15/month) and family ($25–30/month) tiers
6. **Brand polish** — favicon, OG image, the Sikuli Capital footer link should point to a real landing page

## Business model context

Four-tier commercial structure (don't need to act on this, but useful for product decisions):
- Consumer SaaS: ~$10–15/month
- Family/premium: ~$25–30/month
- SMB/business: ~$50–200/month
- White-label B2B licensing to banks, insurance companies, HR platforms, telecoms — the highest-revenue path

## Things to be honest with Carl about

- Dark web *removal* is not a feature we'll ever truthfully offer. The brand commitment is to never claim it.
- HIBP coverage is excellent but not exhaustive — there are breach corpora HIBP doesn't ingest (private Telegram channels, Russian forums, recent unindexed dumps). The product should not overclaim coverage.
- Voice-software friendliness matters — Carl uses Dragon NaturallySpeaking and a SlimBlade trackball. Avoid UI patterns that require precise mouse work or rapid keyboard shortcuts unless there's a voice-friendly alternative.

## Carl's working style

Lead with the data point and the read; skip framework recitation and excessive context-setting. He'll ask for depth if he wants it. Default to acting rather than asking — he prefers `do the thing` over `should I do the thing?`. Treat that as the rule unless an action is irreversible or burns money.
