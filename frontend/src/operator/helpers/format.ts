/** Small display helpers shared by the console's screens. Money is shown, never calculated, in the browser. */
import { money } from "@/sdk";

import type { BadgeTone } from "@/sdk";

/** Per-currency amounts ("KES 1,000.00 · USD 20.00"); a dash when there are none. */
export function moneyMap(amounts: Record<string, string | number> | null | undefined): string {
  const entries = Object.entries(amounts ?? {}).filter(([, v]) => Number(v) !== 0);
  return entries.length ? entries.map(([currency, amount]) => money(amount, currency)).join(" · ") : "-";
}

export const SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "grace", "suspended", "cancelled", "expired", "unmanaged"] as const;

export const STATUS_TONES: Record<string, BadgeTone> = {
  trialing: "info", active: "ok", past_due: "warn", grace: "warn", suspended: "bad", cancelled: "neutral", expired: "bad", unmanaged: "neutral",
};

export const INVOICE_TONES: Record<string, BadgeTone> = { draft: "neutral", issued: "info", paid: "ok", void: "bad" };

export const INTERVALS = ["month", "year", "one_time"] as const;
export type Interval = (typeof INTERVALS)[number];

/** A date input's YYYY-MM-DD as a moment the API takes (start of that day in the browser's time zone); empty stays empty. */
export function dateToIso(date: string): string | null {
  if (!date) return null;
  const moment = new Date(`${date}T00:00:00`);
  return Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}

/** The YYYY-MM-DD a date input shows for a moment from the API. */
export function isoToDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return "";
  return new Date(moment.getTime() - moment.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** "" to undefined, otherwise a whole number (NaN becomes undefined): for optional numeric boxes. */
export function optionalInt(value: string): number | undefined {
  const clean = value.trim();
  if (!clean) return undefined;
  const n = Number(clean);
  return Number.isInteger(n) ? n : undefined;
}

/** Splits a free list ("a, b\nc") into trimmed, non-empty items. */
export function splitList(value: string): string[] {
  return value.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}

/** 1536 -> "1.5 KB" (storage figures). */
export function bytesLabel(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
  return `${i === 0 ? value : value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

/** How full a limit is, 0 to 100 (an unlimited one is never full). */
export function usedPercent(used: number, limit: number | null | undefined): number {
  if (!limit || limit <= 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}
