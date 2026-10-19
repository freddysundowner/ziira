import type { BadgeTone } from "@/sdk";

const MEMBER_TONE: Record<string, BadgeTone> = { active: "ok", paused: "warn", frozen: "warn", cancelled: "neutral", expired: "neutral" };
export const memberTone = (status: string): BadgeTone => MEMBER_TONE[status] ?? "neutral";

const RUN_TONE: Record<string, BadgeTone> = { issued: "ok", pending_review: "info", failed: "bad", skipped: "warn", discarded: "neutral" };
export const runTone = (status: string): BadgeTone => RUN_TONE[status] ?? "neutral";

const SCHEDULE_TONE: Record<string, BadgeTone> = { active: "ok", paused: "warn", ended: "neutral" };
export const scheduleTone = (status: string): BadgeTone => SCHEDULE_TONE[status] ?? "neutral";

const PACKAGE_TONE: Record<string, BadgeTone> = { active: "ok", expired: "neutral", refunded: "neutral" };
export const packageTone = (status: string): BadgeTone => PACKAGE_TONE[status] ?? "neutral";

/** Whole credits show without decimals ("4"), part credits keep what they need ("1.5"). */
export function credits(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return String(value);
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2)));
}

/**
 * Adds decimal strings exactly (whole units of the finest decimal place), for display totals only.
 * The server stays the source of truth for any figure that is stored or invoiced.
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

/** One line of a recurring invoice as a preview: quantity x price less discount (decimal strings in, text out). */
export function linePreview(quantity: string, unitPrice: string, discount = "0"): string {
  const q = Number(quantity), p = Number(unitPrice), d = Number(discount);
  if (![q, p, d].every(Number.isFinite)) return "0.00";
  // cents as whole numbers keep the preview exact for the amounts a person types
  const cents = Math.round(q * p * 100) - Math.round(d * 100);
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

export interface DraftLine { product_id: string; description: string; quantity: string; unit_price: string; discount: string }

export const emptyLine = (): DraftLine => ({ product_id: "", description: "", quantity: "1", unit_price: "", discount: "0" });

export const isLineComplete = (l: DraftLine): boolean => !!l.product_id && Number(l.quantity) > 0 && l.unit_price.trim() !== "" && Number(l.unit_price) >= 0;

/** The total of the lines a person has filled in. */
export const linesTotal = (lines: readonly DraftLine[]): string => sumDecimals(lines.filter(isLineComplete).map((l) => linePreview(l.quantity, l.unit_price, l.discount)));

const INTERVAL_MONTHS: Record<string, number> = { month: 1, quarter: 3, year: 12 };

/** How many months a billing interval covers (a week is not a whole month: 0). */
export const monthsIn = (interval: string): number => INTERVAL_MONTHS[interval] ?? 0;

/** Days from `from` to `to` (both YYYY-MM-DD), whole days, may be negative. */
export function daysBetween(from: string, to: string): number {
  const a = Date.UTC(Number(from.slice(0, 4)), Number(from.slice(5, 7)) - 1, Number(from.slice(8, 10)));
  const b = Date.UTC(Number(to.slice(0, 4)), Number(to.slice(5, 7)) - 1, Number(to.slice(8, 10)));
  return Math.round((b - a) / 86_400_000);
}
