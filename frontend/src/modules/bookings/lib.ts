/** Pure helpers for the calendar: times on the company's clock, positions on the grid, status colours. */

export type Status = "requested" | "confirmed" | "checked_in" | "in_service" | "completed" | "cancelled" | "no_show";
export const STATUSES: readonly Status[] = ["requested", "confirmed", "checked_in", "in_service", "completed", "cancelled", "no_show"];
export const LIVE: readonly Status[] = ["requested", "confirmed", "checked_in", "in_service"];

/** Colours of an appointment block by status (design tokens only). */
export const BLOCK_CLASS: Record<Status, string> = {
  requested: "border-warn/40 bg-warn-soft text-warn",
  confirmed: "border-info bg-info-soft text-info",
  checked_in: "border-brand bg-brand-soft text-brand-strong",
  in_service: "border-brand bg-brand text-brand-ink",
  completed: "border-ok bg-ok-soft text-ok",
  cancelled: "border-line bg-sunken text-muted line-through",
  no_show: "border-bad/40 bg-bad-soft text-bad",
};

export const STATUS_TONE: Record<Status, "warn" | "info" | "brand" | "ok" | "neutral" | "bad"> = {
  requested: "warn", confirmed: "info", checked_in: "brand", in_service: "brand", completed: "ok", cancelled: "neutral", no_show: "bad",
};

export const isStatus = (value: string): value is Status => (STATUSES as readonly string[]).includes(value);

/** The parts of a moment as they read on a wall clock in `zone` (the company's zone; the browser's when unknown). */
function parts(date: Date, zone?: string): { y: number; m: number; d: number; h: number; mi: number } {
  const f = new Intl.DateTimeFormat("en-CA", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  const get = (type: string) => Number(f.formatToParts(date).find((p) => p.type === type)?.value);
  return { y: get("year"), m: get("month"), d: get("day"), h: get("hour"), mi: get("minute") };
}

/** Minutes after midnight, on the wall clock of `zone`. */
export function minutesOfDay(iso: string | Date, zone?: string): number {
  const p = parts(typeof iso === "string" ? new Date(iso) : iso, zone);
  return p.h * 60 + p.mi;
}

/** YYYY-MM-DD of a moment on the wall clock of `zone`. */
export function dayOf(iso: string | Date, zone?: string): string {
  const p = parts(typeof iso === "string" ? new Date(iso) : iso, zone);
  return `${p.y}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")}`;
}

/** The day `n` days after `day` (YYYY-MM-DD). Plain calendar arithmetic, no zone involved. */
export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Monday on or before `day`. */
export function weekStart(day: string): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
  return addDays(day, -weekday);
}

/** Monday is 0, as the API counts weekdays. */
export function weekdayOf(day: string): number {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

/** The moment that reads `hhmm` on `day` in `zone`, as an ISO text with its offset (what the API wants). */
export function zonedIso(day: string, hhmm: string, zone?: string): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  const [h, mi] = hhmm.split(":").map(Number) as [number, number];
  const wanted = Date.UTC(y, m - 1, d, h, mi);
  let guess = wanted;
  for (let i = 0; i < 2; i++) {            // the offset can change across the guess (clock changes), so settle twice
    const p = parts(new Date(guess), zone);
    guess += wanted - Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi);
  }
  const p = parts(new Date(guess), zone);
  const offset = Math.round((Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi) - guess) / 60000);
  const sign = offset < 0 ? "-" : "+";
  const abs = Math.abs(offset);
  return `${day}T${hhmm}:00${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

export const hhmm = (minutes: number): string => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** "09:30" of a moment on the wall clock of `zone`. */
export const clock = (iso: string, zone?: string): string => hhmm(minutesOfDay(iso, zone));

export interface Hour { weekday: number; start_time: string; end_time: string }

const toMinutes = (t: string): number => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));

/** The visible hours of a calendar: from the earliest opening to the latest closing of the visible days, widened to whole hours and to any appointment outside them. */
export function gridRange(hours: Hour[][], days: string[], busy: { start: number; end: number }[]): { start: number; end: number } {
  let start = 24 * 60, end = 0;
  for (const rows of hours) {
    for (const h of rows) {
      if (!days.some((d) => weekdayOf(d) === h.weekday)) continue;
      start = Math.min(start, toMinutes(h.start_time));
      end = Math.max(end, h.end_time.startsWith("23:59") ? 24 * 60 : toMinutes(h.end_time));
    }
  }
  if (end <= start) { start = 8 * 60; end = 18 * 60; }
  for (const b of busy) { start = Math.min(start, b.start); end = Math.max(end, b.end); }
  return { start: Math.floor(start / 60) * 60, end: Math.min(Math.ceil(end / 60) * 60, 24 * 60) };
}

/** Where a block sits in a column, as percentages of the column's height. */
export function place(startMin: number, endMin: number, range: { start: number; end: number }): { top: number; height: number } {
  const span = range.end - range.start;
  const top = Math.max(0, ((startMin - range.start) / span) * 100);
  const bottom = Math.min(100, ((endMin - range.start) / span) * 100);
  return { top, height: Math.max(bottom - top, 1.5) };
}

/** The wall-clock minute under a click at `fraction` (0 to 1) of the column's height, snapped to `step` minutes. */
export function minuteAt(fraction: number, range: { start: number; end: number }, step = 15): number {
  const raw = range.start + Math.min(Math.max(fraction, 0), 0.9999) * (range.end - range.start);
  return Math.floor(raw / step) * step;
}

/** The working stretches (in minutes) of a resource on a day. */
export function workingStretches(hours: Hour[], day: string): { start: number; end: number }[] {
  const weekday = weekdayOf(day);
  return hours.filter((h) => h.weekday === weekday).map((h) => ({ start: toMinutes(h.start_time), end: h.end_time.startsWith("23:59") ? 24 * 60 : toMinutes(h.end_time) }));
}

/** Time off that touches a day, as stretches of that day's minutes. */
export function offStretches(off: { starts_at: string; ends_at: string }[], day: string, zone?: string): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = [];
  for (const o of off) {
    const first = dayOf(o.starts_at, zone), last = dayOf(o.ends_at, zone);
    if (day < first || day > last) continue;
    out.push({ start: day === first ? minutesOfDay(o.starts_at, zone) : 0, end: day === last ? minutesOfDay(o.ends_at, zone) || 24 * 60 : 24 * 60 });
  }
  return out;
}

/** The weekly hours as the editor holds them: a text per weekday with several windows ("09:00-12:00, 13:00-17:00"). */
export function parseWindows(text: string): { start_time: string; end_time: string }[] | null {
  const out: { start_time: string; end_time: string }[] = [];
  for (const piece of text.split(",").map((s) => s.trim()).filter(Boolean)) {
    const m = /^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$/.exec(piece);
    if (!m) return null;
    const a = Number(m[1]) * 60 + Number(m[2]), b = Number(m[3]) * 60 + Number(m[4]);
    if (a >= b || b > 24 * 60 || Number(m[2]) > 59 || Number(m[4]) > 59) return null;
    out.push({ start_time: hhmm(a), end_time: b === 24 * 60 ? "23:59" : hhmm(b) });
  }
  return out;
}

export function windowsText(hours: Hour[], weekday: number): string {
  return hours.filter((h) => h.weekday === weekday).map((h) => `${h.start_time.slice(0, 5)}-${h.end_time.slice(0, 5)}`).join(", ");
}
