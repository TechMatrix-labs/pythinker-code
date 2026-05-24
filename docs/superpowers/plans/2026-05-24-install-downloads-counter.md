# Install Downloads Counter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Count bot-filtered fetches of `pythinker.com/install.sh` and `/install.ps1` at the Cloudflare edge, store the cumulative total in D1, and expose it as a JSON API + a shields.io README badge.

**Architecture:** A Cloudflare Worker bound to the install + API routes runs on every request before cache. For install routes it bot-filters by User-Agent, fetches the script bytes from a separate proxied hostname `dl.pythinker.com` (CDN-cached, honors `stale-if-error`), and on a successful `200` increments an atomic D1 counter via `ctx.waitUntil` (fail-open). API routes read the counter and return JSON / shields-endpoint payloads.

**Tech Stack:** TypeScript, Cloudflare Workers, Wrangler 4, Cloudflare D1 (SQLite), Vitest, shields.io endpoint badge. Spec: `docs/superpowers/specs/2026-05-24-install-downloads-counter-design.md`.

---

## File Structure

```
packages/install-counter-worker/
  package.json          # deps + scripts (mirrors examples/feedback-worker)
  tsconfig.json
  wrangler.jsonc        # routes, D1 binding, DL_HOST var
  vitest.config.ts
  schema.sql            # D1 table + seed row
  src/
    ua.ts               # isInstallUserAgent() — pure, shared with seed script
    badge.ts            # installsJson() / badgeJson() — pure formatters
    counter.ts          # readCount() / incrementCount() — D1 helpers
    index.ts            # Env + fetch router
  test/
    ua.test.ts
    badge.test.ts
    index.test.ts       # routing/count-gating/fail-open with mocked fetch + D1
scripts/
  seed-install-counter.mjs   # one-time CF-analytics backfill (--dry-run, --start)
README.md               # +1 shields endpoint badge line
```

Each `src/*.ts` file has one responsibility; pure functions (`ua`, `badge`) are unit-tested directly, D1/routing is tested in `index.test.ts` with mocks.

---

## Task 0: Branch

- [ ] **Step 1: Create a feature branch** (working tree has unrelated UI edits — leave them untouched)

```bash
git checkout -b feat/install-downloads-counter
```

---

## Task 1: Scaffold the Worker package

**Files:**
- Create: `packages/install-counter-worker/package.json`
- Create: `packages/install-counter-worker/tsconfig.json`
- Create: `packages/install-counter-worker/wrangler.jsonc`
- Create: `packages/install-counter-worker/vitest.config.ts`
- Create: `packages/install-counter-worker/.gitignore`

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "pythinker-install-counter-worker",
  "private": true,
  "version": "0.0.0",
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "test": "vitest run"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20250520.0",
    "typescript": "^5.9.3",
    "vitest": "^2.1.9",
    "wrangler": "^4.45.3"
  }
}
```

- [ ] **Step 2: Create `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "Bundler",
    "lib": ["ES2022"],
    "types": ["@cloudflare/workers-types"],
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src", "test"]
}
```

- [ ] **Step 3: Create `wrangler.jsonc`** (note: paths on the apex use `routes` with `zone_name`, not `custom_domain`; `database_id` filled in Task 8)

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "pythinker-install-counter-worker",
  "main": "src/index.ts",
  "compatibility_date": "2026-05-24",
  "routes": [
    { "pattern": "pythinker.com/install.sh", "zone_name": "pythinker.com" },
    { "pattern": "pythinker.com/install.ps1", "zone_name": "pythinker.com" },
    { "pattern": "pythinker.com/api/installs", "zone_name": "pythinker.com" },
    { "pattern": "pythinker.com/api/installs/badge", "zone_name": "pythinker.com" }
  ],
  "vars": {
    "DL_HOST": "dl.pythinker.com"
  },
  "d1_databases": [
    {
      "binding": "DB",
      "database_name": "install_counter",
      "database_id": "PLACEHOLDER_SET_IN_TASK_8"
    }
  ]
}
```

- [ ] **Step 4: Create `vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "node", include: ["test/**/*.test.ts"] },
});
```

- [ ] **Step 5: Create `.gitignore`**

```
node_modules
.wrangler
.dev.vars
```

- [ ] **Step 6: Install dependencies**

Run: `cd packages/install-counter-worker && npm install`
Expected: `node_modules/` created, no errors. (`npx vitest --version` prints a 2.x version.)

- [ ] **Step 7: Commit**

```bash
git add packages/install-counter-worker/package.json packages/install-counter-worker/tsconfig.json packages/install-counter-worker/wrangler.jsonc packages/install-counter-worker/vitest.config.ts packages/install-counter-worker/.gitignore packages/install-counter-worker/package-lock.json
git commit -m "chore(install-counter): scaffold worker package"
```

---

## Task 2: User-Agent classifier (TDD)

**Files:**
- Create: `packages/install-counter-worker/src/ua.ts`
- Test: `packages/install-counter-worker/test/ua.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// test/ua.test.ts
import { describe, expect, it } from "vitest";
import { isInstallUserAgent } from "../src/ua";

describe("isInstallUserAgent", () => {
  it("counts curl, wget, powershell", () => {
    expect(isInstallUserAgent("curl/8.5.0")).toBe(true);
    expect(isInstallUserAgent("Wget/1.21.4")).toBe(true);
    expect(isInstallUserAgent("WindowsPowerShell/5.1")).toBe(true);
    expect(isInstallUserAgent("Mozilla/5.0 ... PowerShell/7.4.0")).toBe(true);
  });

  it("skips browsers, bots, empty", () => {
    expect(isInstallUserAgent("Mozilla/5.0 (X11) Chrome/124")).toBe(false);
    expect(isInstallUserAgent("Googlebot/2.1")).toBe(false);
    expect(isInstallUserAgent("")).toBe(false);
    expect(isInstallUserAgent(null)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/install-counter-worker && npx vitest run test/ua.test.ts`
Expected: FAIL — cannot find module `../src/ua`.

- [ ] **Step 3: Write minimal implementation**

```ts
// src/ua.ts
// Real curl|bash / irm installs send curl, wget, or PowerShell agents.
// Browsers and crawlers are excluded. Vanity filter — not spoof-proof.
const INSTALL_UA = /(^curl\/)|(^Wget\/)|(PowerShell)/i;

export function isInstallUserAgent(ua: string | null): boolean {
  return ua != null && INSTALL_UA.test(ua);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/ua.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/install-counter-worker/src/ua.ts packages/install-counter-worker/test/ua.test.ts
git commit -m "feat(install-counter): add install User-Agent classifier"
```

---

## Task 3: Badge + JSON formatters (TDD)

**Files:**
- Create: `packages/install-counter-worker/src/badge.ts`
- Test: `packages/install-counter-worker/test/badge.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// test/badge.test.ts
import { describe, expect, it } from "vitest";
import { badgeJson, installsJson } from "../src/badge";

describe("formatters", () => {
  it("installsJson returns the raw count", () => {
    expect(installsJson(12345)).toEqual({ installs: 12345 });
    expect(installsJson(null)).toEqual({ installs: null });
  });

  it("badgeJson is shields-endpoint shaped with thousands separators", () => {
    expect(badgeJson(12345)).toEqual({
      schemaVersion: 1,
      label: "installs",
      message: "12,345",
      color: "blue",
    });
  });

  it("badgeJson degrades to a valid non-empty message when count unknown", () => {
    const b = badgeJson(null);
    expect(b.schemaVersion).toBe(1);
    expect(b.message).toBe("unknown");
    expect(b.color).toBe("lightgrey");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/badge.test.ts`
Expected: FAIL — cannot find module `../src/badge`.

- [ ] **Step 3: Write minimal implementation**

```ts
// src/badge.ts
export function installsJson(count: number | null) {
  return { installs: count };
}

export function badgeJson(count: number | null) {
  if (count == null) {
    return { schemaVersion: 1, label: "installs", message: "unknown", color: "lightgrey" };
  }
  return {
    schemaVersion: 1,
    label: "installs",
    message: count.toLocaleString("en-US"),
    color: "blue",
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run test/badge.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/install-counter-worker/src/badge.ts packages/install-counter-worker/test/badge.test.ts
git commit -m "feat(install-counter): add badge/json formatters"
```

---

## Task 4: D1 counter helpers

**Files:**
- Create: `packages/install-counter-worker/src/counter.ts`
- Create: `packages/install-counter-worker/schema.sql`

- [ ] **Step 1: Create `schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO counter (id, n) VALUES (1, 0);
```

- [ ] **Step 2: Create `src/counter.ts`**

```ts
// src/counter.ts
import type { D1Database } from "@cloudflare/workers-types";

// Single atomic statement — concurrent fetches do not race.
export async function incrementCount(db: D1Database): Promise<void> {
  await db.prepare("UPDATE counter SET n = n + 1 WHERE id = 1").run();
}

// Returns null if the row/DB is unavailable, so callers can degrade gracefully.
export async function readCount(db: D1Database): Promise<number | null> {
  const row = await db.prepare("SELECT n FROM counter WHERE id = 1").first<{ n: number }>();
  return row?.n ?? null;
}
```

- [ ] **Step 3: Type-check**

Run: `cd packages/install-counter-worker && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add packages/install-counter-worker/src/counter.ts packages/install-counter-worker/schema.sql
git commit -m "feat(install-counter): add D1 counter helpers + schema"
```

---

## Task 5: Worker router (TDD)

**Files:**
- Create: `packages/install-counter-worker/src/index.ts`
- Test: `packages/install-counter-worker/test/index.test.ts`

- [ ] **Step 1: Write the failing test** (mocks `fetch` for the origin subrequest and a minimal D1)

```ts
// test/index.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";

type Stmt = { run: () => Promise<void>; first: () => Promise<{ n: number } | null> };

function makeEnv(opts: { n?: number; throwOnWrite?: boolean } = {}) {
  const run = vi.fn(async () => {
    if (opts.throwOnWrite) throw new Error("D1 down");
  });
  const first = vi.fn(async () => ({ n: opts.n ?? 0 }));
  const prepare = vi.fn((_sql: string): Stmt => ({ run, first }));
  return { env: { DB: { prepare }, DL_HOST: "dl.pythinker.com" } as any, run, prepare };
}

function ctx() {
  const promises: Promise<unknown>[] = [];
  return { waitUntil: (p: Promise<unknown>) => promises.push(p), _promises: promises } as any;
}

const ORIGIN_BODY = "#!/bin/sh\necho install\n";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(ORIGIN_BODY, { status: 200 })),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("worker router", () => {
  it("increments for a curl UA on a 200 install fetch and serves the script", async () => {
    const { env, run } = makeEnv();
    const c = ctx();
    const res = await worker.fetch(
      new Request("https://pythinker.com/install.sh", { headers: { "user-agent": "curl/8.5.0" } }),
      env,
      c,
    );
    await Promise.all(c._promises);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(ORIGIN_BODY);
    expect(run).toHaveBeenCalledTimes(1);
    // subrequest hit DL_HOST, never the proxied route (loopback guard)
    expect((fetch as any).mock.calls[0][0]).toContain("dl.pythinker.com/install.sh");
  });

  it("does NOT increment for a browser UA", async () => {
    const { env, run } = makeEnv();
    const c = ctx();
    await worker.fetch(
      new Request("https://pythinker.com/install.sh", { headers: { "user-agent": "Mozilla/5.0 Chrome/124" } }),
      env,
      c,
    );
    await Promise.all(c._promises);
    expect(run).not.toHaveBeenCalled();
  });

  it("does NOT increment when origin returns non-200", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 502 })));
    const { env, run } = makeEnv();
    const c = ctx();
    const res = await worker.fetch(
      new Request("https://pythinker.com/install.sh", { headers: { "user-agent": "curl/8" } }),
      env,
      c,
    );
    await Promise.all(c._promises);
    expect(res.status).toBe(502);
    expect(run).not.toHaveBeenCalled();
  });

  it("does NOT increment for a non-GET method", async () => {
    const { env, run } = makeEnv();
    const c = ctx();
    await worker.fetch(
      new Request("https://pythinker.com/install.sh", { method: "HEAD", headers: { "user-agent": "curl/8" } }),
      env,
      c,
    );
    await Promise.all(c._promises);
    expect(run).not.toHaveBeenCalled();
  });

  it("is fail-open: a D1 write error still serves the script", async () => {
    const { env } = makeEnv({ throwOnWrite: true });
    const c = ctx();
    const res = await worker.fetch(
      new Request("https://pythinker.com/install.sh", { headers: { "user-agent": "curl/8" } }),
      env,
      c,
    );
    await Promise.all(c._promises); // must not reject
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(ORIGIN_BODY);
  });

  it("/api/installs returns JSON with CORS", async () => {
    const { env } = makeEnv({ n: 12345 });
    const res = await worker.fetch(new Request("https://pythinker.com/api/installs"), env, ctx());
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(await res.json()).toEqual({ installs: 12345 });
  });

  it("/api/installs/badge returns shields-endpoint JSON", async () => {
    const { env } = makeEnv({ n: 12345 });
    const res = await worker.fetch(new Request("https://pythinker.com/api/installs/badge"), env, ctx());
    expect(await res.json()).toEqual({
      schemaVersion: 1,
      label: "installs",
      message: "12,345",
      color: "blue",
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run test/index.test.ts`
Expected: FAIL — cannot find module `../src/index`.

- [ ] **Step 3: Write the implementation**

```ts
// src/index.ts
import type { D1Database, ExecutionContext } from "@cloudflare/workers-types";
import { badgeJson, installsJson } from "./badge";
import { incrementCount, readCount } from "./counter";
import { isInstallUserAgent } from "./ua";

export interface Env {
  DB: D1Database;
  DL_HOST: string;
}

const INSTALL_PATHS = new Set(["/install.sh", "/install.ps1"]);

function json(body: unknown, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json; charset=utf-8", ...extraHeaders },
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/api/installs") {
      const n = await safeRead(env);
      return json(installsJson(n), { "access-control-allow-origin": "*" });
    }

    if (path === "/api/installs/badge") {
      const n = await safeRead(env);
      return json(badgeJson(n), { "cache-control": "public, max-age=300" });
    }

    if (INSTALL_PATHS.has(path)) {
      // Fetch bytes from the proxied download host (CDN-cached, honors
      // stale-if-error). Never fetch the proxied install route itself.
      const origin = `https://${env.DL_HOST}${path}${url.search}`;
      const res = await fetch(origin, request);

      const eligible =
        request.method === "GET" &&
        res.status === 200 &&
        isInstallUserAgent(request.headers.get("user-agent"));

      if (eligible) {
        // Scheduled without awaiting; may continue after the response returns.
        ctx.waitUntil(incrementCount(env.DB).catch(() => {}));
      }
      return res;
    }

    return new Response("Not found", { status: 404 });
  },
};

async function safeRead(env: Env): Promise<number | null> {
  try {
    return await readCount(env.DB);
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run`
Expected: PASS — all `ua`, `badge`, `index` tests green.

- [ ] **Step 5: Type-check**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add packages/install-counter-worker/src/index.ts packages/install-counter-worker/test/index.test.ts
git commit -m "feat(install-counter): add worker router with count gating + fail-open"
```

---

## Task 6: Seed script (CF analytics backfill)

**Files:**
- Create: `scripts/seed-install-counter.mjs`

- [ ] **Step 1: Create the script**

```js
#!/usr/bin/env node
// One-time backfill: seed the D1 counter from the last N days of bot-filtered
// /install.sh + /install.ps1 fetches in Cloudflare GraphQL Analytics.
//
// Usage:
//   CF_API_TOKEN=... CF_ZONE_TAG=... node scripts/seed-install-counter.mjs --dry-run
//   CF_API_TOKEN=... CF_ZONE_TAG=... node scripts/seed-install-counter.mjs        # writes via wrangler
//   node scripts/seed-install-counter.mjs --start 1000                            # manual fallback, no API
//
// Caveat: CF analytics dataset availability/lookback/sampling vary by plan;
// the seed is approximate. Use --start when analytics are unavailable.
import { execFileSync } from "node:child_process";

const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const startIdx = args.indexOf("--start");
const manualStart = startIdx >= 0 ? Number(args[startIdx + 1]) : null;
const DAYS = 30;

// Mirrors src/ua.ts — keep in sync.
const INSTALL_UA = /(^curl\/)|(^Wget\/)|(PowerShell)/i;

async function fetchAnalyticsCount() {
  const token = process.env.CF_API_TOKEN;
  const zone = process.env.CF_ZONE_TAG;
  if (!token || !zone) throw new Error("CF_API_TOKEN and CF_ZONE_TAG are required (or use --start N)");

  const since = new Date(Date.now() - DAYS * 864e5).toISOString();
  const until = new Date().toISOString();
  const query = `query($zone:String!,$since:Time!,$until:Time!){
    viewer{zones(filter:{zoneTag:$zone}){
      httpRequestsAdaptiveGroups(
        limit:10000,
        filter:{datetime_geq:$since,datetime_leq:$until,
          clientRequestPath_in:["/install.sh","/install.ps1"],
          clientRequestHTTPMethodName:"GET"}
      ){count dimensions{userAgent}}
    }}}`;

  const r = await fetch("https://api.cloudflare.com/client/v4/graphql", {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ query, variables: { zone, since, until } }),
  });
  const data = await r.json();
  if (data.errors?.length) throw new Error(JSON.stringify(data.errors));
  const groups = data.data.viewer.zones[0]?.httpRequestsAdaptiveGroups ?? [];
  return groups
    .filter((g) => INSTALL_UA.test(g.dimensions.userAgent ?? ""))
    .reduce((sum, g) => sum + g.count, 0);
}

const seed = manualStart != null ? manualStart : await fetchAnalyticsCount();
console.log(`Computed seed value: ${seed}`);

if (dryRun) {
  console.log("--dry-run: not writing.");
  process.exit(0);
}

execFileSync(
  "npx",
  ["wrangler", "d1", "execute", "install_counter", "--remote",
   "--command", `UPDATE counter SET n = ${Number(seed)} WHERE id = 1`],
  { cwd: "packages/install-counter-worker", stdio: "inherit" },
);
console.log(`Counter seeded to ${seed}.`);
```

- [ ] **Step 2: Smoke-check arg parsing offline**

Run: `node scripts/seed-install-counter.mjs --start 1000 --dry-run`
Expected: prints `Computed seed value: 1000` then `--dry-run: not writing.` and exits 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/seed-install-counter.mjs
git commit -m "feat(install-counter): add CF-analytics seed script"
```

---

## Task 7: README badge

**Files:**
- Modify: `README.md` (badge block near the existing Downloads badge, ~line 17)

- [ ] **Step 1: Add the badge line** immediately after the existing Downloads badge line

```markdown
[![Installs](https://img.shields.io/endpoint?url=https://pythinker.com/api/installs/badge&cacheSeconds=300)](https://pythinker.com)
```

- [ ] **Step 2: Verify the line is present**

Run: `grep -n "api/installs/badge" README.md`
Expected: one match in the badge block.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add install count badge to README"
```

---

## Task 8: Provision on Cloudflare (browser + wrangler, with user)

> This task is interactive. Code is committed; now wire up infra. The user
> drives login and approves the production DNS change.

- [ ] **Step 1: Authenticate wrangler** (opens browser; user logs in to Cloudflare)

Run: `cd packages/install-counter-worker && npx wrangler login`
Expected: browser OAuth → "Successfully logged in."

- [ ] **Step 2: Create the D1 database**

Run: `npx wrangler d1 create install_counter`
Expected: prints `database_id`. **Copy it into `wrangler.jsonc` `database_id`** (replace `PLACEHOLDER_SET_IN_TASK_8`), then commit:

```bash
git add packages/install-counter-worker/wrangler.jsonc
git commit -m "chore(install-counter): bind created D1 database id"
```

- [ ] **Step 3: Apply the schema (remote D1)**

Run: `npx wrangler d1 execute install_counter --remote --file ./schema.sql`
Expected: success; `SELECT n FROM counter WHERE id=1` returns 0.

- [ ] **Step 4: Create `dl.pythinker.com` DNS record (browser, user-approved)**

Via Chrome DevTools MCP, open the Cloudflare dashboard → pythinker.com → DNS.
Add: **Type** `A`/`AAAA` (or `CNAME`) → **Name** `dl` → **Target** the same
origin the VPS uses for `pythinker.com` → **Proxy status: Proxied (orange)**.
**Show the exact values to the user and get explicit confirmation before saving.**
Then verify the VPS serves the script for this host:

Run: `curl -fsSI https://dl.pythinker.com/install.sh`
Expected: `200`, `content-type: text/x-shellscript`. (If the VPS vhosts by Host
header, ensure it answers for `dl.pythinker.com` too — operational fix on the VPS.)

- [ ] **Step 5: Deploy the Worker**

Run: `npx wrangler deploy`
Expected: deploy succeeds; the 4 routes on pythinker.com are registered.

- [ ] **Step 6: Create a read-only Analytics API token (browser)**

Via the dashboard → My Profile → API Tokens → Create Token → permission
**Account Analytics: Read** (or zone Analytics: Read). Copy the token + the zone
tag (Overview page) for the seed step. Do not commit them.

- [ ] **Step 7: Seed the counter (dry-run first)**

```bash
CF_API_TOKEN=*** CF_ZONE_TAG=*** node scripts/seed-install-counter.mjs --dry-run
CF_API_TOKEN=*** CF_ZONE_TAG=*** node scripts/seed-install-counter.mjs
```
Expected: dry-run prints a plausible count; real run seeds D1. (If analytics
return nothing, use `--start <N>`.)

---

## Task 9: End-to-end verification

- [ ] **Step 1: Count increments for curl, not browsers**

```bash
curl -fsS -o /dev/null https://pythinker.com/install.sh   # curl UA → counts
A=$(curl -fsS https://pythinker.com/api/installs | python -c "import sys,json;print(json.load(sys.stdin)['installs'])")
curl -fsS -o /dev/null -A "Mozilla/5.0 Chrome/124" https://pythinker.com/install.sh  # browser → no count
B=$(curl -fsS https://pythinker.com/api/installs | python -c "import sys,json;print(json.load(sys.stdin)['installs'])")
echo "before=$A after_browser=$B (expect equal)"
```
Expected: the browser fetch does not change the count; a curl fetch does (allow a moment for the async write).

- [ ] **Step 2: Badge endpoint is shields-valid**

Run: `curl -fsS https://pythinker.com/api/installs/badge`
Expected: `{"schemaVersion":1,"label":"installs","message":"…","color":"blue"}`.

- [ ] **Step 3: Install still works (fail-open + caching)**

Run: `curl -fsSL https://pythinker.com/install.sh | head -5`
Expected: the real install script bytes (unchanged behavior).

- [ ] **Step 4: README badge renders** — open the repo README on GitHub; the Installs badge shows the count.

- [ ] **Step 5: Final commit / PR**

```bash
git push -u origin feat/install-downloads-counter
```
Open a PR referencing the spec and this plan.

---

## Self-Review notes

- **Spec coverage:** edge capture (T5), UA bot-filter (T2), D1 single-row atomic counter + schema (T4), proxied `dl.pythinker.com` fetch + stale-if-error via CDN (T5/T8), count-only-on-GET-200 (T5 tests), fail-open (T5 test), `/api/installs` + badge with CORS/cache (T5), seed with `--dry-run`/`--start`/sampling caveat (T6), README badge (T7), DNS/token/deploy ops (T8). ✓
- **Hot-row caveat / WAE-DO fallback:** documented in spec; not built (YAGNI). ✓
- **Type consistency:** `isInstallUserAgent`, `installsJson`, `badgeJson`, `readCount`, `incrementCount`, `Env{DB,DL_HOST}` used identically across tasks. ✓
- **UA regex duplicated** in `src/ua.ts` and the seed script — intentional (different runtimes); comment flags "keep in sync". ✓
```
