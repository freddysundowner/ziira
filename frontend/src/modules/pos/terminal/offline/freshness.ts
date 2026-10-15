/** How old the copy of prices and stock kept on this device is, and when to fetch a new one. */

export const REFRESH_AFTER_MS = 5 * 60_000;
export const AGING_AFTER_MS = 30 * 60_000;
export const STALE_AFTER_MS = 12 * 60 * 60_000;

export type Freshness = "fresh" | "aging" | "stale" | "none";

export function freshnessOf(fetchedAt: number | null | undefined, now: number): Freshness {
  if (!fetchedAt) return "none";
  const age = now - fetchedAt;
  if (age > STALE_AFTER_MS) return "stale";
  return age > AGING_AFTER_MS ? "aging" : "fresh";
}

/** Fetch a new copy when there is none or the one we have is a few minutes old (and only when there is a connection). */
export function needsRefresh(fetchedAt: number | null | undefined, now: number, online: boolean): boolean {
  if (!online) return false;
  return !fetchedAt || now - fetchedAt >= REFRESH_AFTER_MS;
}

/** Show "prices as of ..." when selling without a connection or from an old copy. */
export function showAsOf(freshness: Freshness, online: boolean): boolean {
  return freshness !== "none" && (!online || freshness !== "fresh");
}
