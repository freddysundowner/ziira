import type { BadgeTone } from "@/sdk";

/**
 * Adds decimal strings exactly (as whole units of the finest decimal place), for display totals only.
 * The server stays the source of truth for any figure that is stored or posted.
 */
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

/** What is past its due date: everything owed except the part not yet due. */
export function overdueOf(buckets: Record<string, string>): string {
  return sumDecimals(Object.entries(buckets).filter(([k]) => k !== "not_due").map(([, v]) => v));
}

export const isPositive = (value: string | null | undefined): boolean => Number(value) > 0;

const CUSTOMER_TONE: Record<string, BadgeTone> = { active: "ok", on_hold: "warn", inactive: "neutral" };
export const customerTone = (status: string): BadgeTone => CUSTOMER_TONE[status] ?? "neutral";

const LEAD_TONE: Record<string, BadgeTone> = { new: "info", contacted: "brand", qualified: "ok", converted: "ok", lost: "bad" };
export const leadTone = (status: string): BadgeTone => LEAD_TONE[status] ?? "neutral";

const CREDIT_TONE: Record<string, BadgeTone> = { active: "ok", approved: "ok", pending: "warn", pending_approval: "warn", rejected: "bad", superseded: "neutral" };
export const creditTone = (status: string): BadgeTone => CREDIT_TONE[status] ?? "neutral";

/** Is a follow-up past its due time and not done? */
export function isOverdueActivity(a: { due_at: string | null; done_at: string | null }, now = new Date()): boolean {
  return !a.done_at && !!a.due_at && new Date(a.due_at) < now;
}

/** YYYY-MM-DDTHH:mm from a date input to an ISO string the API accepts (local time), or null when empty. */
export function dueToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
