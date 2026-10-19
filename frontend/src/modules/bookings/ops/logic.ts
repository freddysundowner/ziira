/** Pure helpers for the front-desk operations screens: week ranges, report periods, grouping. No DOM, no requests. */
import { addDays, dayOf, weekStart, zonedIso } from "../lib";

/** A week (Monday to Sunday) around `day`, and the moments that bound it on the company's clock. */
export function weekBounds(day: string, zone?: string): { first: string; last: string; startIso: string; endIso: string } {
  const first = weekStart(day);
  return { first, last: addDays(first, 6), startIso: zonedIso(first, "00:00", zone), endIso: zonedIso(addDays(first, 7), "00:00", zone) };
}

/** The seven days of the week that starts on `first`. */
export const weekDays = (first: string): string[] => Array.from({ length: 7 }, (_, i) => addDays(first, i));

/** Sessions grouped by their day on the company's clock, days in order, each day's sessions by start time. */
export function groupByDay<T extends { starts_at: string }>(rows: readonly T[], zone?: string): { day: string; rows: T[] }[] {
  const map = new Map<string, T[]>();
  for (const r of rows) {
    const d = dayOf(r.starts_at, zone);
    map.set(d, [...(map.get(d) ?? []), r]);
  }
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, list]) => ({ day, rows: [...list].sort((a, b) => a.starts_at.localeCompare(b.starts_at)) }));
}

export type Period = "thisMonth" | "lastMonth" | "custom";

/** First and last day of the month `offset` months from the month of `day` (YYYY-MM-DD). */
export function monthRange(day: string, offset = 0): { start: string; end: string } {
  const [y, m] = day.split("-").map(Number) as [number, number];
  const first = new Date(Date.UTC(y, m - 1 + offset, 1));
  const last = new Date(Date.UTC(y, m + offset, 0));
  return { start: first.toISOString().slice(0, 10), end: last.toISOString().slice(0, 10) };
}

/** The dates of a report period preset; "custom" keeps what the person typed. */
export function periodRange(kind: Period, day: string, custom: { start: string; end: string }): { start: string; end: string } {
  if (kind === "thisMonth") return monthRange(day, 0);
  if (kind === "lastMonth") return monthRange(day, -1);
  return custom.end < custom.start ? { start: custom.start, end: custom.start } : custom;
}

/** Colour of the "days overdue" badge: just due is calm, long overdue is loud. */
export function overdueTone(days: number): "info" | "warn" | "bad" {
  return days <= 7 ? "info" : days <= 30 ? "warn" : "bad";
}

/** A whole number of weeks between 1 and 52 from what was typed (anything else becomes 1). */
export function clampWeeks(text: string): number {
  const n = Math.floor(Number(text));
  return Number.isFinite(n) ? Math.min(52, Math.max(1, n)) : 1;
}

/** A positive whole number or null (an empty box means "use the default"). */
export function wholeOrNull(text: string): number | null {
  const n = Math.floor(Number(text));
  return text.trim() !== "" && Number.isFinite(n) && n >= 1 ? n : null;
}

/** The first of the week's working windows of a day as text ("09:00-17:00"), several joined; empty when off. */
export const windowsLabel = (windows: readonly string[]): string => windows.join(" · ");

/** Moment at midnight on `day` and at midnight the next day, for time off covering whole days. */
export function wholeDays(from: string, to: string, zone?: string): { startsAt: string; endsAt: string } {
  const last = to < from ? from : to;
  return { startsAt: zonedIso(from, "00:00", zone), endsAt: zonedIso(addDays(last, 1), "00:00", zone) };
}
