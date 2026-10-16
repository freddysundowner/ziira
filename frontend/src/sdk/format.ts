/**
 * Showing numbers and dates. Values from the API are decimal strings: parse only to display, never to calculate money
 * (the backend owns the arithmetic). The currency is the company's, never assumed.
 */
// The company's time zone: every time a person sees is on the company's clock, not the browser's, so a receipt, a list
// and a report agree wherever the screen is opened. Set once the company is known (see `useCompanies`).
let zone: string | undefined;
const zoneListeners = new Set<() => void>();

/** Use this IANA time zone (for example the company's `timezone`) for every date shown. An unknown name is ignored. */
export function setDisplayTimeZone(name: string | null | undefined): void {
  let next: string | undefined;
  try { next = name ? new Intl.DateTimeFormat(undefined, { timeZone: name }).resolvedOptions().timeZone : undefined; } catch { next = undefined; }
  if (next === zone) return;
  zone = next;
  zoneListeners.forEach((fn) => fn());
}

export const getDisplayTimeZone = (): string | undefined => zone;
export function subscribeDisplayTimeZone(fn: () => void): () => void {
  zoneListeners.add(fn);
  return () => { zoneListeners.delete(fn); };
}

const lang = () => (typeof document !== "undefined" ? document.documentElement.lang : "") || undefined;

export function money(value: string | number | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  try {
    return new Intl.NumberFormat(lang(), currency ? { style: "currency", currency } : { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  } catch {
    return `${currency ?? ""} ${n.toFixed(2)}`.trim();
  }
}

export function quantity(value: string | number | null | undefined, maxDigits = 3): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? new Intl.NumberFormat(lang(), { maximumFractionDigits: maxDigits }).format(n) : String(value);
}

/** A percentage; `digits` fixes the number of decimals (otherwise up to two). */
export function percent(value: string | number | null | undefined, digits?: number): string {
  const n = Number(value);
  const options = digits === undefined ? { maximumFractionDigits: 2 } : { minimumFractionDigits: digits, maximumFractionDigits: digits };
  return value !== null && value !== undefined && value !== "" && Number.isFinite(n) ? `${new Intl.NumberFormat(lang(), options).format(n)}%` : "—";
}

export function formatDate(value: string | Date | null | undefined, withTime = false): string {
  if (!value) return "—";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  // A plain calendar date (2026-03-05) has no time: show that day whatever the zone, never the day before.
  const calendarDay = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
  const timeZone = calendarDay ? "UTC" : zone;
  return new Intl.DateTimeFormat(lang(), { ...(withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }), timeZone }).format(d);
}

/** Today as YYYY-MM-DD on the company's clock (the browser's until it is known): what a date input holds. */
export function today(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function monthStart(): string {
  return `${today().slice(0, 8)}01`;
}

/** "snake_case" or "kebab-case" to "Snake case", for statuses the backend sends as codes. */
export function humanise(code: string | null | undefined): string {
  if (!code) return "—";
  const s = code.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
