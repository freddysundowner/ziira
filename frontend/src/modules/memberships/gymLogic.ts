/** Pure helpers for the gym screens: check-in results, the kiosk, access windows, report shading. No React, no requests. */
import type { Schemas } from "@/sdk";

import type { RosterEntry } from "./offline";
import { decideFromRoster } from "./offline";

// ------------------------------------------------------------------------------------------------ check-in results

export type Outcome = "allow" | "warn" | "deny";
export type CheckinResult = Schemas["CheckinResultOut"];
export type CheckinReason = Schemas["CheckinReasonOut"];

export const asOutcome = (value: string | null | undefined): Outcome => (value === "allow" || value === "warn" ? value : "deny");

/** Everything the result panel shows, whether the answer came from the server or from the saved list. */
export interface ResultView {
  outcome: Outcome;
  headline: string;
  reasons: { code: string; message: string; level: string }[];
  customerId: string | null;
  name: string | null;
  number: string | null;
  plan: string | null;
  photoUrl: string | null;
  owed: number;
  creditsLeft: string | null;
  duplicate: boolean;
  overridden: boolean;
  canOverride: boolean;
  needsTerms: boolean;
  notFound: boolean;
  /** Set when the answer was worked out on this device from the saved list: the time the list was saved. */
  offlineSavedAt: number | null;
}

export function viewFromServer(r: CheckinResult): ResultView {
  const outcome = r.allowed ? (r.outcome === "warn" ? "warn" : "allow") : "deny";
  return {
    outcome,
    headline: r.message,
    reasons: r.reasons.map((x) => ({ code: x.code, message: x.message, level: x.level })),
    customerId: r.person?.customer_id ?? null,
    name: r.person?.name ?? null,
    number: r.person?.number ?? null,
    plan: r.person?.plan_name ?? r.entitlement ?? null,
    photoUrl: r.person?.photo_link ?? null,
    owed: Number(r.person?.owed ?? 0),
    creditsLeft: r.credits_left ?? null,
    duplicate: r.duplicate || r.reasons.some((x) => x.code === "already_in"),
    overridden: r.overridden,
    canOverride: r.can_override,
    needsTerms: r.reasons.some((x) => x.code === "waiver_missing"),
    notFound: r.person === null && r.code === "not_found",
    offlineSavedAt: null,
  };
}

export function viewFromRoster(entry: RosterEntry, savedAt: number): ResultView {
  const d = decideFromRoster(entry);
  return {
    outcome: d.outcome,
    headline: d.message,
    reasons: [{ code: d.code, message: d.message, level: d.outcome }],
    customerId: entry.customer_id ?? null,
    name: entry.name ?? null,
    number: entry.number,
    plan: entry.plan,
    photoUrl: null,
    owed: 0,
    creditsLeft: null,
    duplicate: false,
    overridden: false,
    canOverride: false,
    needsTerms: d.code === "waiver_missing",
    notFound: false,
    offlineSavedAt: savedAt,
  };
}

/** Initials for a person without a photo ("Jane Wanjiru" gives "JW"). */
export function initials(name: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

/**
 * What a typed or scanned text is: an identifier (member number, card, QR text, phone) when it has no spaces and holds a digit;
 * otherwise a name to search for.
 */
export function looksLikeIdentifier(text: string): boolean {
  const s = text.trim();
  return s.length > 0 && !/\s/.test(s) && /\d/.test(s);
}

/** "08:05" for a time in milliseconds since 1970, on this device's clock. */
export function clockTime(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// ------------------------------------------------------------------------------------------------ kiosk

const KIOSK_REASONS = new Set([
  "blocked", "no_membership", "not_started", "ended", "on_hold", "frozen", "classes_only", "wrong_branch", "outside_hours", "payment_overdue",
  "waiver_missing", "no_credits", "not_found", "payment_late", "expiring",
]);

/** The plain-words key for the screen a member sees (no money, no personal data). Unknown codes get the generic one. */
export function kioskReasonKey(code: string): string {
  return KIOSK_REASONS.has(code) ? code : "generic";
}

export interface KioskView {
  outcome: Outcome;
  firstName: string | null;
  reasonKey: string | null;
  needsTerms: boolean;
  customerId: string | null;
}

export function kioskView(r: CheckinResult): KioskView {
  const v = viewFromServer(r);
  const hard = r.reasons.find((x) => x.level === "deny")?.code ?? r.code;
  return {
    outcome: v.outcome,
    firstName: v.name ? (v.name.trim().split(/\s+/)[0] ?? null) : null,
    reasonKey: v.outcome === "allow" ? null : v.outcome === "warn" ? kioskReasonKey(r.reasons.find((x) => x.level === "warn")?.code ?? "") : kioskReasonKey(hard),
    needsTerms: v.needsTerms,
    customerId: v.customerId,
  };
}

// ------------------------------------------------------------------------------------------------ access windows

export interface AccessWindow { days: number[]; from: string; to: string }

/** Windows as the plan stores them (days 0 = Monday ... 6 = Sunday); anything malformed is ignored. */
export function readWindows(rules: readonly Record<string, unknown>[] | null | undefined): AccessWindow[] {
  return (rules ?? []).map((r) => ({
    days: Array.isArray(r.days) ? (r.days as unknown[]).filter((d): d is number => typeof d === "number" && d >= 0 && d <= 6) : [],
    from: typeof r.from === "string" ? r.from : "06:00",
    to: typeof r.to === "string" ? r.to : "22:00",
  }));
}

export const newWindow = (): AccessWindow => ({ days: [0, 1, 2, 3, 4], from: "06:00", to: "22:00" });

/** A problem with the windows a person typed (a key into the translations), or null. */
export function windowsProblem(windows: readonly AccessWindow[]): "days" | "times" | null {
  for (const w of windows) {
    if (w.days.length === 0) return "days";
    if (!/^\d{2}:\d{2}$/.test(w.from) || !/^(\d{2}:\d{2}|24:00)$/.test(w.to) || w.from >= w.to) return "times";
  }
  return null;
}

export const toggleDay = (days: readonly number[], day: number): number[] => (days.includes(day) ? days.filter((d) => d !== day) : [...days, day].sort((a, b) => a - b));

// ------------------------------------------------------------------------------------------------ reports

export interface HeatCell { weekday: number; hour: number; visits: number }

/** A weekday x hour grid of visits, only the hours that matter (the busiest span, at least 6 to 21). */
export function heatGrid(cells: readonly HeatCell[]): { hours: number[]; rows: number[][]; max: number; total: number } {
  let lo = 6;
  let hi = 21;
  for (const c of cells) { lo = Math.min(lo, c.hour); hi = Math.max(hi, c.hour); }
  const hours: number[] = [];
  for (let h = lo; h <= hi; h++) hours.push(h);
  const rows = Array.from({ length: 7 }, () => hours.map(() => 0));
  let max = 0;
  let total = 0;
  for (const c of cells) {
    const row = rows[c.weekday];
    if (!row || c.hour < lo || c.hour > hi) continue;
    row[c.hour - lo] = (row[c.hour - lo] ?? 0) + c.visits;
    max = Math.max(max, row[c.hour - lo] ?? 0);
    total += c.visits;
  }
  return { hours, rows, max, total };
}

/** 0 (none) to 1: how strong a cell is shaded. Stepped, not continuous, so levels are easy to tell apart. */
export function intensity(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 0;
  return Math.max(0.15, Math.ceil((value / max) * 5) / 5);
}

/** The busiest weekday and hour, for a one-line text summary of the heat map. */
export function busiest(cells: readonly HeatCell[]): HeatCell | null {
  let best: HeatCell | null = null;
  for (const c of cells) if (!best || c.visits > best.visits) best = c;
  return best && best.visits > 0 ? best : null;
}

/** Shading for a retention percentage (0 to 100); null (not yet known) is not shaded. */
export const retentionIntensity = (pct: number | null): number => (pct === null ? 0 : Math.max(0.1, Math.ceil(pct / 20) / 5));

/** Background colour from a design token at an intensity, so it follows the light and dark themes. */
export const tokenShade = (token: "brand" | "ok" | "warn" | "bad", level: number): string | undefined => (level > 0 ? `rgb(var(--${token}) / ${(level * 0.7).toFixed(2)})` : undefined);

/** Percent of `part` in `whole`, whole number, 0 when there is no whole. */
export const share = (part: number, whole: number): number => (whole > 0 ? Math.round((part * 100) / whole) : 0);

/** ISO date n days before `from` (YYYY-MM-DD). */
export function daysAgo(from: string, n: number): string {
  const d = new Date(Date.UTC(Number(from.slice(0, 4)), Number(from.slice(5, 7)) - 1, Number(from.slice(8, 10))));
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

// ------------------------------------------------------------------------------------------------ money

/** Whole days a date is in the past relative to `today` (both YYYY-MM-DD); 0 or negative: not late. */
export function lateDays(dueDate: string | null | undefined, today: string): number {
  if (!dueDate) return 0;
  const a = Date.UTC(Number(dueDate.slice(0, 4)), Number(dueDate.slice(5, 7)) - 1, Number(dueDate.slice(8, 10)));
  const b = Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 1, Number(today.slice(8, 10)));
  return Math.round((b - a) / 86_400_000);
}

/** Settle states of an invoice that still need money. */
export const owesMoney = (outstanding: string | number | null | undefined): boolean => Number(outstanding ?? 0) > 0;

/** Plan kind tone words used by badges. */
export const KIND_ORDER = ["recurring", "fixed_term", "pass"] as const;

/** A decimal-looking text for an amount field: digits and one dot only; "" stays "". */
export const cleanAmount = (text: string): string => text.replace(/[^\d.]/g, "").replace(/(\..*?)\./g, "$1");

/** Splits a list of codes typed or pasted (commas, spaces or new lines), trimmed, without repeats. */
export function splitCodes(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean))];
}

// ------------------------------------------------------------------------------------------------ owner report

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};
const rec = (v: unknown): Record<string, unknown> => (v && typeof v === "object" ? (v as Record<string, unknown>) : {});

export interface Report {
  start: string;
  end: string;
  members: { active: number; paused: number; frozen: number; trials: number; cancelling: number; inactive: number };
  mrr: string;
  atRisk: string;
  atRiskPercent: number;
  byPlan: { plan: string; members: number; mrr: string }[];
  flow: { month: string; new: number; ended: number; net: number }[];
  retention: { month: string; joined: number; percent: (number | null)[] }[];
  attendance: HeatCell[];
  visits: number;
  visitors: number;
  owed: { owed: string; people: number; d7: string; d30: string; d60: string; d60plus: string };
  holds: { holds: number; days: number; fees: string; running: number };
  trials: { started: number; converted: number };
  leaving: { reason: string; members: number }[];
  classes: { name: string; sessions: number; booked: number; places: number; fill: number }[];
  trainers: { trainer: string; sessions: number; earned: string }[];
}

/** The report as the screen uses it: numbers are numbers and nothing is undefined, whatever the server left out. */
export function parseReport(raw: Schemas["MembershipOwnerReportOut"]): Report {
  const m = raw.members;
  const a = rec(raw.arrears);
  const f = rec(raw.freezes);
  return {
    start: raw.start, end: raw.end,
    members: { active: num(m.active), paused: num(m.paused), frozen: num(m.frozen), trials: num(m.trials), cancelling: num(m.cancelling), inactive: num(m.inactive_4_weeks) },
    mrr: raw.mrr, atRisk: raw.revenue_at_risk, atRiskPercent: raw.revenue_at_risk_percent,
    byPlan: raw.by_plan.map((r) => ({ plan: String(r.plan ?? ""), members: num(r.members), mrr: String(r.mrr ?? "0") })),
    flow: raw.flow.map((r) => ({ month: String(r.month ?? ""), new: num(r.new), ended: num(r.ended), net: num(r.net) })),
    retention: raw.retention.map((r) => ({
      month: String(r.month ?? ""), joined: num(r.joined),
      percent: Array.isArray(r.still_member_percent) ? (r.still_member_percent as unknown[]).map((x) => (x === null || x === undefined ? null : num(x))) : [],
    })),
    attendance: raw.attendance.map((r) => ({ weekday: num(r.weekday), hour: num(r.hour), visits: num(r.visits) })),
    visits: raw.visits, visitors: raw.visitors,
    owed: { owed: String(a.owed ?? "0"), people: num(a.people), d7: String(a.d7 ?? "0"), d30: String(a.d30 ?? "0"), d60: String(a.d60 ?? "0"), d60plus: String(a.d60plus ?? "0") },
    holds: { holds: num(f.holds), days: num(f.days), fees: String(f.fees ?? "0"), running: num(f.running) },
    trials: { started: num(raw.trials.started), converted: num(raw.trials.converted) },
    leaving: raw.leaving.map((r) => ({ reason: String(r.reason ?? ""), members: num(r.members) })),
    classes: (raw.class_fill ?? []).map((r) => ({ name: String(r.class ?? ""), sessions: num(r.sessions), booked: num(r.booked), places: num(r.places), fill: num(r.fill_percent) })),
    trainers: raw.trainers.map((r) => ({ trainer: String(r.trainer ?? ""), sessions: num(r.sessions), earned: String(r.earned ?? "0") })),
  };
}

/** The width of a bar (0 to 100) for a value against the largest in its list. */
export const barWidth = (value: number, max: number): number => (max > 0 ? Math.max(value > 0 ? 3 : 0, Math.round((value * 100) / max)) : 0);

/** "Jan 26" for a date like 2026-01-01, on the reader's language. */
export function monthLabel(date: string): string {
  const d = new Date(`${date.slice(0, 7)}-01T12:00:00`);
  return Number.isNaN(d.getTime()) ? date : d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}
