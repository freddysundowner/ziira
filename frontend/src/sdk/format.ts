/**
 * Showing numbers and dates. Values from the API are decimal strings: parse only to display, never to calculate money
 * (the backend owns the arithmetic). The currency is the company's, never assumed.
 */
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

export function percent(value: string | number | null | undefined): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${new Intl.NumberFormat(lang(), { maximumFractionDigits: 2 }).format(n)}%` : "—";
}

export function formatDate(value: string | Date | null | undefined, withTime = false): string {
  if (!value) return "—";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(lang(), withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(d);
}

/** Today as YYYY-MM-DD in the browser's time zone (what a date input holds). */
export function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
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
