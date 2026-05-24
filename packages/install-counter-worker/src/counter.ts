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
