import type { BadgeTone } from "@/sdk";

/** Adds decimal strings exactly, for display totals only (the server stays the source of truth for stored figures). */
export function sumDecimals(values: readonly (string | number | null | undefined)[]): string {
  const parsed = values.map((v) => String(v ?? "0").trim() || "0");
  const places = Math.max(0, ...parsed.map((v) => (v.split(".")[1] ?? "").length));
  const total = parsed.reduce((acc, v) => {
    const negative = v.startsWith("-");
    const [whole = "0", frac = ""] = v.replace("-", "").split(".");
    const scaled = BigInt(whole + frac.padEnd(places, "0"));
    return acc + (negative ? -scaled : scaled);
  }, 0n);
  const sign = total < 0n ? "-" : "";
  const digits = (total < 0n ? -total : total).toString().padStart(places + 1, "0");
  return places === 0 ? `${sign}${digits}` : `${sign}${digits.slice(0, -places)}.${digits.slice(-places)}`;
}

/** A payment prompt is settled once it is in one of these states; until then the screen keeps asking. */
export const FINAL_INTENT = ["succeeded", "failed", "cancelled", "timeout"] as const;
export const isFinalIntent = (status: string): boolean => (FINAL_INTENT as readonly string[]).includes(status);
export const hasPending = (rows: readonly { status: string }[] | undefined): boolean => !!rows?.some((r) => !isFinalIntent(r.status));

const INTENT_TONE: Record<string, BadgeTone> = { pending: "warn", succeeded: "ok", failed: "bad", cancelled: "neutral", timeout: "bad" };
export const intentTone = (status: string): BadgeTone => INTENT_TONE[status] ?? "neutral";

const MATCH_TONE: Record<string, BadgeTone> = { unmatched: "warn", proposed: "info", matched: "ok", ignored: "neutral", applied: "ok", undone: "neutral" };
export const matchTone = (status: string): BadgeTone => MATCH_TONE[status] ?? "neutral";

const CLOSE_TONE: Record<string, BadgeTone> = { open: "info", submitted: "warn", locked: "ok", reopened: "warn" };
export const closeTone = (status: string): BadgeTone => CLOSE_TONE[status] ?? "neutral";

/** Money taken in minus money paid out, per payment method, for a list of payments (a display summary). */
export function summarise(payments: readonly { direction: string; method: string; amount: string; status: string }[]) {
  const live = payments.filter((p) => p.status !== "reversed");
  const incoming = live.filter((p) => p.direction === "in");
  const methods = [...new Set(incoming.map((p) => p.method))];
  return {
    count: live.length,
    received: sumDecimals(incoming.map((p) => p.amount)),
    paidOut: sumDecimals(live.filter((p) => p.direction === "out").map((p) => p.amount)),
    byMethod: methods.map((m) => ({ method: m, amount: sumDecimals(incoming.filter((p) => p.method === m).map((p) => p.amount)) })),
  };
}

export interface TotalLine { path: string[]; value: string }

/** Flatten the daily close's nested figures ({ cash: { expected: "10" } }) into rows a table can show. */
export function flattenTotals(totals: Record<string, unknown>, prefix: string[] = []): TotalLine[] {
  return Object.entries(totals).flatMap(([key, value]) => {
    if (value && typeof value === "object") return flattenTotals(value as Record<string, unknown>, [...prefix, key]);
    return [{ path: [...prefix, key], value: value === null || value === undefined ? "" : String(value) }];
  });
}

export const looksNumeric = (value: string): boolean => /^-?\d+(\.\d+)?$/.test(value);
