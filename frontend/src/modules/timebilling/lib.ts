/** Pure rules of the Time and Billing screens: durations, weeks, the week grid, the timer clock, line totals. */

import type { Entry } from "./types";

// --- durations ---------------------------------------------------------------------------------------------------
const DAY_MINUTES = 1440;
/** The most a budget, balance or capacity box accepts: far more than a day. */
export const LONG_MINUTES = 6_000_000;

/**
 * What a person types in a time box, as minutes: "1.5" and "1,5" (hours), "1:30", ":45", "90m", "1h", "1h 30m", "2h15".
 * A bare number means hours. Empty means 0 (clear the cell). Returns null for text that is not a time or is over `max` minutes (a day).
 */
export function parseDuration(text: string, max = DAY_MINUTES): number | null {
  const s = text.trim().toLowerCase().replace(/,/g, ".");
  if (s === "") return 0;
  let minutes: number | null = null;
  let m: RegExpExecArray | null;
  if ((m = /^(\d*):(\d{1,2})$/.exec(s))) {
    minutes = Number(m[1] || 0) * 60 + Number(m[2]);
    if (Number(m[2]) > 59) return null;
  } else if ((m = /^(\d+(?:\.\d+)?|\.\d+)$/.exec(s))) {
    minutes = Math.round(Number(m[1]) * 60);
  } else if ((m = /^(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)$/.exec(s))) {
    minutes = Math.round(Number(m[1]) * 60);
  } else if ((m = /^(\d+)\s*(?:m|min|mins|minute|minutes)$/.exec(s))) {
    minutes = Number(m[1]);
  } else if ((m = /^(\d+)\s*(?:h|hr|hrs|hours?)\s*(\d+)\s*(?:m|min|mins|minutes?)?$/.exec(s))) {
    if (Number(m[2]) > 59) return null;
    minutes = Number(m[1]) * 60 + Number(m[2]);
  }
  return minutes !== null && Number.isFinite(minutes) && minutes <= max ? minutes : null;
}

/** Snap minutes to the business's step (halves go up); a little time is never rounded away to nothing. */
export function snapMinutes(minutes: number, step: number): number {
  if (step <= 1 || minutes <= 0) return Math.max(minutes, 0);
  const low = Math.floor(minutes / step) * step;
  const rounded = (minutes - low) * 2 >= step ? low + step : low;
  return Math.min(rounded > 0 ? rounded : step, DAY_MINUTES);
}

/** "1h 30m", "2h", "45m", "0m": how long, in words people use. */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  const m = Math.max(0, Math.round(minutes));
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h && rest) return `${h}h ${rest}m`;
  return h ? `${h}h` : `${rest}m`;
}

/** "1:30" for a box a person edits; empty for nothing. */
export function formatClock(minutes: number): string {
  if (minutes <= 0) return "";
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

// --- dates -------------------------------------------------------------------------------------------------------
const parts = (iso: string): [number, number, number] => {
  const [y = 1970, m = 1, d = 1] = iso.split("-").map(Number);
  return [y, m, d];
};
const fromUtc = (d: Date): string => d.toISOString().slice(0, 10);

export function addDays(iso: string, days: number): string {
  const [y, m, d] = parts(iso);
  return fromUtc(new Date(Date.UTC(y, m - 1, d + days)));
}

/** First day of the week that holds `iso`; `startsOn` is 1 (Monday) to 7 (Sunday), as in the settings. */
export function weekStartOf(iso: string, startsOn: number): string {
  const [y, m, d] = parts(iso);
  const isoWeekday = ((new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7) + 1;
  return addDays(iso, -((isoWeekday - startsOn + 7) % 7));
}

export const weekDays = (start: string): string[] => Array.from({ length: 7 }, (_, i) => addDays(start, i));

/** Short weekday name of a calendar day, in the page language. */
export function dayName(iso: string, style: "short" | "long" = "short"): string {
  const [y, m, d] = parts(iso);
  const lang = (typeof document !== "undefined" ? document.documentElement.lang : "") || undefined;
  return new Intl.DateTimeFormat(lang, { weekday: style, timeZone: "UTC" }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** Day of the month, "5". */
export const dayNumber = (iso: string): string => String(parts(iso)[2]);

/** First day of the month `months` away from `iso`'s month. */
export function monthStartOf(iso: string, months = 0): string {
  const [y, m] = parts(iso);
  return fromUtc(new Date(Date.UTC(y, m - 1 + months, 1)));
}

// --- the week grid -----------------------------------------------------------------------------------------------
export type GridEntry = Pick<Entry, "project_id" | "project_code" | "project_name" | "task" | "work_date" | "minutes" | "billable" | "source">;

export interface GridCell { total: number; own: number }
export interface GridRow {
  key: string;
  project_id: string;
  project_code: string;
  project_name: string;
  task: string | null;
  billable: boolean;
  cells: Record<string, GridCell>;
}
export type RowSeed = Pick<GridRow, "project_id" | "project_code" | "project_name" | "task" | "billable">;

const cleanTask = (task: string | null | undefined): string | null => (task ?? "").trim().slice(0, 120) || null;

export const rowKey = (projectId: string, task: string | null | undefined, billable: boolean): string => `${projectId}|${cleanTask(task) ?? ""}|${billable ? 1 : 0}`;

/**
 * Rows of the grid: one per (project, task, billable) with minutes per day. A cell counts every entry of that
 * row and day; `own` is the part the grid itself saved (timer and quick-log entries are the rest and are edited separately).
 */
export function buildRows(entries: readonly GridEntry[], seeds: readonly RowSeed[] = []): GridRow[] {
  const rows = new Map<string, GridRow>();
  const ensure = (s: RowSeed): GridRow => {
    const key = rowKey(s.project_id, s.task, s.billable);
    let row = rows.get(key);
    if (!row) {
      row = { key, project_id: s.project_id, project_code: s.project_code, project_name: s.project_name, task: cleanTask(s.task), billable: s.billable, cells: {} };
      rows.set(key, row);
    }
    return row;
  };
  for (const e of entries) {
    const cell = (ensure(e).cells[e.work_date] ??= { total: 0, own: 0 });
    cell.total += e.minutes;
    if (e.source === "grid") cell.own += e.minutes;
  }
  seeds.forEach(ensure);
  return [...rows.values()].sort((a, b) => a.project_code.localeCompare(b.project_code) || (a.task ?? "").localeCompare(b.task ?? "") || Number(b.billable) - Number(a.billable));
}

export const rowTotal = (row: GridRow, days: readonly string[]): number => days.reduce((sum, d) => sum + (row.cells[d]?.total ?? 0), 0);
export const dayTotals = (rows: readonly GridRow[], days: readonly string[]): number[] => days.map((d) => rows.reduce((sum, r) => sum + (r.cells[d]?.total ?? 0), 0));

/**
 * The minutes the grid should store for a cell when the person types `typed` as the day's total: what is typed
 * minus the time that came from the timer or quick log. Null when the typed total is below that time.
 */
export function gridMinutesFor(typed: number, cell: GridCell | undefined): number | null {
  const others = (cell?.total ?? 0) - (cell?.own ?? 0);
  return typed >= others ? typed - others : null;
}

// --- the timer ---------------------------------------------------------------------------------------------------
/** Seconds on the timer now: what the server counted when we asked, plus the time since if it is running. */
export function elapsedNow(base: { elapsed_seconds: number; running: boolean }, askedAtMs: number, nowMs: number): number {
  return base.elapsed_seconds + (base.running ? Math.max(0, Math.floor((nowMs - askedAtMs) / 1000)) : 0);
}

/** "0:05:09": hours, minutes, seconds. */
export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** A timer that has run this long was most likely forgotten. */
export const FORGOTTEN_AFTER_SECONDS = 12 * 3600;
export const looksForgotten = (seconds: number): boolean => seconds >= FORGOTTEN_AFTER_SECONDS;

// --- money previews and bars -------------------------------------------------------------------------------------
/** hours x rate for a preview while typing (the server's figure is shown after saving). Null when either is not a number. */
export function linePreview(minutes: number | null | undefined, rate: string | null | undefined): string | null {
  const r = Number(rate);
  if (minutes === null || minutes === undefined || rate === null || rate === undefined || rate === "" || !Number.isFinite(r)) return null;
  return (Math.round((minutes * r * 100) / 60) / 100).toFixed(2);
}

/** A percentage kept inside 0..100 for the width of a bar. */
export const barWidth = (value: number | string | null | undefined): number => {
  const n = Number(value);
  return Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : 0;
};

/** The ageing columns the API names, in order, with the key of each in the translations. */
export const AGE_BUCKETS = [
  { api: "0-30", key: "d30" },
  { api: "31-60", key: "d60" },
  { api: "61-90", key: "d90" },
  { api: "over 90", key: "older" },
] as const;
