# Install Downloads Counter — Design

**Date:** 2026-05-24
**Status:** Approved (brainstorming) — pending implementation plan

## Problem

Pythinker is installed via `curl -fsSL https://pythinker.com/install.sh | bash`
(and `irm https://pythinker.com/install.ps1 | iex` on Windows). There is no
count of how many times the install script is fetched. We want a **bot-filtered
fetch count**, surfaced as a **README badge** and a **raw JSON API endpoint**.

## Constraints & key facts

- **Cloudflare fronts the VPS.** `pythinker.com` is proxied by Cloudflare; the
  origin is a self-hosted VPS that serves the script (backed by
  `scripts/install-native.sh`).
- **Edge caching makes origin logs useless for counting.** The install endpoint
  is served with `Cache-Control: public, max-age=300, s-maxage=900,
  stale-if-error=86400`. Most fetches are served from Cloudflare's edge cache
  and never reach the VPS, so VPS access logs would massively undercount. The
  count **must** happen at the edge, in a Worker that runs on every request
  before cache.
- **Vanity metric, not audited.** UA-based bot filtering blocks honest browsers
  and crawlers, but not a deliberate `curl -A 'curl/8.5.0'` loop. This counter
  is accepted as a vanity/marketing number, not a tamper-resistant metric. This
  limitation is intentional and documented.

## Alternatives considered (hosted platforms)

There is **no passive "pepy for install scripts"**: pepy works only because PyPI
centralizes downloads in public BigQuery logs. Shell-script installs have no
central registry, so no hosted service can observe the count without us capturing
it at our own edge. Edge caching also means VPS/origin-log-based tools undercount.
So the Worker (edge capture + bot filter) is required regardless; the only thing
a hosted platform could replace is the **storage/badge layer**:

- **Abacus** (CountAPI successor) / CounterAPI — free counter APIs with native
  shields badges. Rejected as the primary store: a free hobby counter
  disappearing (as CountAPI did) would silently break a flagship README badge,
  and it moves the number off our infra.
- **GoatCounter / Plausible** — full privacy analytics; overkill for one number
  and heavier to operate.
- **Cloudflare Workers Analytics Engine** — already considered as "Approach B"
  (rolling-window, not cumulative).

**Decision: own the number in D1.** For a permanent headline metric, data
ownership and no third-party dependency outweigh the zero-ops appeal of a free
hosted counter. D1's hot-row caveat does not bite at install-script volume.

## Chosen approach

A Cloudflare Worker bound to the install + API routes increments an atomic D1
counter on each non-bot fetch, then serves the script bytes from a DNS-only
origin hostname. The badge and JSON API read the same counter.

### Architecture

```
curl/irm ──> CF edge ──> Worker(/install.sh, /install.ps1)
                           │  GET + UA bot-filter (curl/wget/powershell ⇒ real install)
                           │  fetch https://pythinker.com/<script> {cf:{cacheTtl:300}}
                           │     └─ same-zone subrequest ⇒ CF sends straight to VPS origin (no recursion)
                           │  on 200 with body ⇒ ctx.waitUntil(D1: UPDATE counter SET n=n+1)  ← fail-open
                           └─ return script bytes (503 "exit 1" shellscript if origin unreachable)
shields.io ─> /api/installs/badge ─> D1 SELECT n ─> {schemaVersion,label,message,color}
tooling   ─> /api/installs        ─> D1 SELECT n ─> {"installs": N}
```

The Worker fetches the script from the **apex** (`https://pythinker.com/<script>`).
Cloudflare documents that **routes cannot be the target of a same-zone `fetch()`**
— a same-zone subrequest is sent **directly to the origin**, bypassing the Worker
route. So this does **not** recurse, needs **no extra hostname**, and the origin
receives `Host: pythinker.com` (which it serves; it 404s other hosts). The VPS
remains the single source of truth. `cf: { cacheEverything: true, cacheTtl: 300 }`
lets the edge cache the script to keep origin load low.

> **Why not a separate `dl.pythinker.com` hostname (earlier draft)?** Two reasons
> discovered during implementation: (1) the VPS routes by `Host` header and
> **404s any host other than `pythinker.com`**, so `dl` would need a VPS-side
> vhost change (no SSH available); (2) the same-zone-fetch rule already routes
> the apex subrequest to origin without recursion, making a second hostname
> unnecessary. **Confirmed regression (post-deploy `cf-cache-status: DYNAMIC`):**
> same-zone subrequests are **not** edge-cached, so each install fetch reaches the
> VPS (previously `install.sh` was edge-cached) and `stale-if-error=86400` no
> longer applies. At install-script volume the extra origin load is negligible.
> During a VPS outage users get a clean `503` (`exit 1` shellscript) instead of
> last-good bytes — a small, graceful degradation (never a 1101 error page). If
> origin load ever matters, recover caching with the Workers Cache API
> (`caches.default`) — deferred (YAGNI).

## Components

- **`packages/install-counter-worker/`** — new Worker package, mirroring the
  conventions of `examples/feedback-worker/` (TypeScript, `wrangler.jsonc`,
  `Env` interface, `export default { fetch }`).
  - **`wrangler.jsonc`** — routes for `pythinker.com/install.sh`,
    `pythinker.com/install.ps1`, `pythinker.com/api/installs`,
    `pythinker.com/api/installs/badge`; one D1 binding `DB`.
  - **`src/index.ts`** — request router:
    - install routes → bot-filter, `ctx.waitUntil` increment, serve from origin
    - api routes → read counter, return JSON
  - **`package.json`** — `dev` / `deploy` scripts, `wrangler` + `typescript`
    devDeps (match feedback-worker versions).
- **D1 database `install_counter`** — single-row counter:
  ```sql
  CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0);
  INSERT INTO counter (id, n) VALUES (1, 0);
  ```
  D1 processes writes single-threaded per database, and every install fetch
  hits the same hot row. This is acceptable for expected low-volume install
  traffic. **If D1 overload errors appear under spikes, switch to Workers
  Analytics Engine or a batched Durable Object aggregator** — recorded here as
  the documented escalation path, not built now.
- **`scripts/seed-install-counter.mjs`** — one-time backfill. Queries the
  Cloudflare GraphQL Analytics API (`httpRequestsAdaptiveGroups`) for the last
  ~30 days of bot-filtered `/install.sh` + `/install.ps1` requests and writes
  the result as the starting `n`. Requirements:
  - Applies the **same UA classifier** as the Worker (one shared module), so
    the seed is consistent with forward counting.
  - Supports `--dry-run` (print the computed seed, write nothing) and a manual
    `--start <N>` override for when analytics are unavailable.
  - Requires a read-only CF analytics API token, passed via env var, never
    committed.
  - **Caveat:** CF GraphQL dataset availability, lookback, and sampling vary by
    plan; the seed is approximate and may be limited or unavailable. The manual
    `--start` fallback exists precisely for this.
- **README badge** — one new shields.io `endpoint` badge next to the existing
  Downloads badge:
  `https://img.shields.io/endpoint?url=https://pythinker.com/api/installs/badge`.

## Data flow & bot filter

- **Count only a real, served install.** A fetch is counted only when *all* of
  these hold: method is `GET`; UA matches the install classifier; the origin/CDN
  response is `200` with a body successfully obtained. `HEAD`, `OPTIONS`, health
  checks, non-200s, and origin/cache failures are **not** counted — this avoids
  counting failed fetches as installs.
- Real installs send `User-Agent` of `curl/*`, `Wget/*`, or PowerShell
  (`WindowsPowerShell`, `PowerShell`). Only these are counted; browsers,
  Googlebot, uptime monitors, etc. are skipped. The matcher is a single regex
  constant in a shared module (also used by the seed script), unit-tested.
- After a successful `200` response, the increment is scheduled as
  `ctx.waitUntil(env.DB.prepare("UPDATE counter SET n = n + 1 WHERE id = 1").run().catch(…))`
  — scheduled without awaiting, so it may continue after the response is
  returned and never delays or breaks the install pipe. `UPDATE … n = n + 1` is
  a single atomic SQL statement, so concurrent fetches do not race.
- `/api/installs` → `{"installs": N}`, `Content-Type: application/json`,
  `Access-Control-Allow-Origin: *`, `GET` only.
- `/api/installs/badge` → `{"schemaVersion": 1, "label": "installs",
  "message": "12,345", "color": "blue"}` (thousands-formatted, non-empty
  `message`), `Content-Type: application/json`, served with
  `Cache-Control: public, max-age=300`, `GET` only.

## Error handling (fail-open is the rule)

- **D1 write throws** → swallowed via `.catch` inside `waitUntil`; the install
  response is unaffected. A counter outage must never break installs. (Under a
  D1 spike/overload some increments may be dropped — acceptable for a vanity
  counter; see the WAE/DO escalation path above.)
- **Origin fetch fails** → the `fetch()` is wrapped in `try/catch`; on a thrown
  error (origin unreachable) the Worker returns a graceful `503` shellscript
  (`# install temporarily unavailable\nexit 1`) rather than letting the Worker
  throw (which would surface a Cloudflare `1101` error page to `curl | bash`).
  A failed fetch is **not** counted (no `200`). See the accepted `stale-if-error`
  regression noted under Architecture.
- **D1 read fails on `/api/*`** → return `200` with `message: "unknown"` / grey
  color for the badge (keeps the shields.io payload valid) and
  `{"installs": null}` for the JSON endpoint.

## Testing

- **Unit:** UA classifier — `curl/8.5.0`, `Wget/1.21`, PowerShell ⇒ counted;
  Chrome, Googlebot, empty UA ⇒ skipped.
- **Unit:** badge JSON shape + thousands formatting; `/api/installs` shape +
  `Access-Control-Allow-Origin: *` header.
- **Behavior:** count gating — non-`GET` (HEAD/OPTIONS) and non-`200` origin
  responses do **not** increment; only a `GET` + matching UA + `200` does.
- **Behavior:** simulated D1 throw ⇒ install response still `200` with script
  bytes (fail-open).
- **Behavior:** subrequest targets `DL_HOST`, never the proxied `pythinker.com`
  install route (loopback guard).
- **Integration:** `wrangler dev` with local D1 — curl each route, assert the
  counter increments for a `curl` UA and does not for a browser UA.

## Out of scope (logged, not built)

- Per-OS / daily breakdowns (single total counter only).
- Unique-install dedup (raw fetch count, not distinct hosts).
- Completed-install beacons (counts fetches, not successful installs).
- A live number rendered on pythinker.com (badge + API only).

## Open operational tasks (for the plan, not the code)

- Create the D1 database and bind it; run the schema migration.
- Provision a read-only CF analytics API token for the seed script.
- Run the seed script once (`--dry-run` first) before announcing the badge.
