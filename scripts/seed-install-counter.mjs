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
