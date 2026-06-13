# Magpie → Erdo product launch runbook

Turning Magpie from "Niall's personal hosted instance + OSS repo" into a proper
Erdo-owned product: published packages, Erdo infra, real auth, and the brand domain.

**Model decided:** Niall's current Railway instance stays as his *personal self-hosted*
deployment (valid OSS use case — don't touch/delete it). The Erdo product instance is
built **fresh** in Erdo infra, no data migration.

Legend: 🤖 = I can do it in-session · 🧑 = needs Niall (login/account/$$) · 🤝 = together

---

## Decisions to lock first (blockers)

1. **Database platform** 🧑 — **Neon** (if Erdo standardizes there) vs **Railway Postgres**.
   - Neon: you create the DB + enable `pgvector`, hand me `DATABASE_URL`. Fits Erdo if it's the house standard.
   - Railway Postgres: I provision it end-to-end in the Erdo workspace (same as today).
   - *Recommendation:* match whatever Erdo already uses; if no standard, Railway Postgres is the zero-extra-step option.

2. **Clerk scope** 🤝 — the big one (see Phase C). Two options:
   - **(A) Web-login only** — Clerk replaces email-OTP for the UI; Magpie keeps its own orgs/membership + API keys + MCP OAuth. *Smaller, faster, lower risk.*
   - **(B) Clerk as source of truth** — Clerk Organizations back Magpie orgs/roles; Magpie syncs from Clerk. *Bigger re-architecture; better long-term for B2B/B2B2C.*
   - *Recommendation:* ship **(A)** for launch, design toward **(B)**. Decide before any auth code.

3. **magpie.ai acquisition** 🧑 — pursue the broker deal now (5-figure) or launch on `magpie.erdo.ai` and flip later. *Recommendation:* launch on subdomain, pursue `.ai` in parallel — `MAGPIE_PUBLIC_URL` makes the flip a config change.

4. **Docs domain** 🤝 — `docs.magpie.erdo.ai` (Mintlify) vs keep docs in-app. *Recommendation:* Mintlify on `docs.magpie.erdo.ai`.

---

## Phase A — Publish packages

Names are already renamed in-repo: npm `@erdo/magpie`, pip `erdo-magpie` (both confirmed free; `@magpie` org and `magpie-ai` PyPI name are taken by others).

- [ ] 🧑 Confirm the **`@erdo` npm org** exists / is yours (couldn't verify via API).
- [ ] 🤖 Build the CLI (`cd cli && npm run build`), set `files`/`bin`/`repository` in `package.json`, dry-run `npm publish --access public`.
- [ ] 🧑 `npm login` (+ 2FA) → 🤖 `npm publish --access public` for `@erdo/magpie`.
- [ ] 🤖 Build the Python dist (`python -m build`), verify `erdo-magpie` metadata.
- [ ] 🧑 PyPI token → 🤖 `twine upload` `erdo-magpie`.
- [ ] 🤖 Smoke test: `npx @erdo/magpie@latest --help`, `pipx run erdo-magpie version`.

## Phase B — Erdo infrastructure (fresh instance)

- [ ] 🧑 Re-auth Railway to the Erdo account (`railway logout` → `railway login` as `niall@thenuggets.app`).
- [ ] 🤖 New `magpie` project in the Erdo Railway workspace; connect GitHub `erdoai/magpie@main` (auto-deploy, Dockerfile builder) — same pattern as the personal one.
- [ ] 🤝 Provision **Postgres** per decision #1 (+ `pgvector`); run `magpie migrate`.
- [ ] 🧑 Create an **R2 bucket** in the Erdo Cloudflare account → 🤖 set `STORAGE_*` + `ASSET_PUBLIC_BASE_URL`.
- [ ] 🤖 Set env vars: `DATABASE_URL`, `OPENAI_API_KEY`, `SESSION_SECRET`, `STORAGE_*`, `MAGPIE_PUBLIC_URL`, (`RESEND_*` or Clerk per Phase C).
- [ ] 🤖 Verify deploy is healthy (REST + MCP + UI); seed nothing (clean instance).

## Phase C — Auth (Clerk)

Current auth: email-OTP (Resend) + 30-day session cookies, per-user/scoped **API keys** (for agents), and an **OAuth issuer** for the remote MCP server. Clerk has to slot into this without breaking agent keys or MCP.

**If option (A) web-login only:**
- [ ] 🧑 Create Clerk app; get publishable + secret keys.
- [ ] 🤖 Web UI: add Clerk React, gate the app, replace the OTP login screen.
- [ ] 🤖 Backend: verify Clerk session JWT on web requests; map Clerk user → Magpie `users` row (create-on-first-login).
- [ ] 🤖 Keep API keys + MCP OAuth as-is. Email/OTP code path retired for humans (or left as fallback).
- [ ] 🤖 Update `docs/site/reference/auth.mdx` + configuration.

**Toward option (B) later:** map Clerk Organizations → Magpie orgs/roles, sync membership via Clerk webhooks, make Clerk the identity source. Design doc before coding.

> Note: if Clerk owns human login, the earlier "verify a Resend domain so OTP reaches outside users" blocker **goes away** — Clerk sends the email. Only keep Resend if we keep OTP as a fallback.

## Phase D — Domains

- [ ] 🤖 Add `magpie.erdo.ai` as a custom domain on the **Erdo** Railway service → get CNAME target.
- [ ] 🧑/🤖 Set the Cloudflare CNAME `magpie.erdo.ai` → Railway target (erdo.ai DNS is on Cloudflare).
- [ ] 🤖 Set `MAGPIE_PUBLIC_URL=https://magpie.erdo.ai`; verify the landing page + app serve there.
- [ ] 🤝 Mintlify: connect `docs/site`, set `docs.magpie.erdo.ai`, verify build.
- [ ] 🧑 (parallel) Broker outreach for `magpie.ai`.

## Phase E — Launch-readiness follow-ups (post-cutover)

From the B2B2C assessment — not blockers for a soft launch, but needed before inviting real companies:

- [ ] Postgres backups (managed or scheduled `pg_dump`).
- [ ] Per-org quotas (entries, attachments, embedding calls) + basic rate limiting.
- [ ] Usage page + admin org/user inspection.
- [ ] Audit log (who-did-what within an org).
- [ ] Defense-in-depth: consider Postgres RLS behind the app-layer org filters.

---

## Done already (this session)

- Landing page: collections spotlight, read-time resolution demo, "Stays coherent" section, copy fixes.
- Coherence feature (dedupe-on-write / find_duplicates / merge) shipped across REST, both MCP servers, both CLIs, and docs (`concepts/coherence`).
- Full MCP tool parity (16 tools on both servers).
- Package rename in-repo: `@erdo/magpie` + `erdo-magpie`.
- Self-hosting guide + `docker-compose.yml`; corrected stale 5→16 tool count.
- Personal Railway instance: auto-deploy from `main` wired (Dockerfile builds `web/dist`).
