import type { Schemas } from "@/sdk";

export type Preview = Schemas["PreviewOut"];
export type FieldGuess = Schemas["FieldGuessOut"];

/** What the file picker and the drop zone accept. */
export const ACCEPT = ".pdf,.xlsx,.csv,.txt,.png,.jpg,.jpeg,application/pdf,text/csv,image/png,image/jpeg";
const EXTENSIONS = ["pdf", "xlsx", "csv", "txt", "png", "jpg", "jpeg"];
export const MAX_MB = 10;

/** Why a chosen file cannot be used before it is even sent: "type", "size", or null when it may go. */
export function refuseFile(file: Pick<File, "name" | "size">): "type" | "size" | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!EXTENSIONS.includes(ext)) return "type";
  return file.size > MAX_MB * 1024 * 1024 ? "size" : null;
}

/** A file waiting to be read once its connection exists (the "just drop it" start of the wizard). */
let pending: { file: File; password: string } | null = null;
export const keepPendingFile = (file: File, password: string) => { pending = { file, password }; };
export function takePendingFile() {
  const found = pending;
  pending = null;
  return found;
}

/** Large amounts in short form ("KES 1.2M") for the one-line summary; the exact figures stay in the detail. */
export function compactMoney(value: string | null | undefined, currency: string | undefined, locale: string): string {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return "—";
  try {
    return new Intl.NumberFormat(locale, { ...(currency ? { style: "currency", currency } : {}), notation: "compact", maximumFractionDigits: 1 }).format(n);
  } catch {
    return String(n);
  }
}

/** "03/04/2026" read both ways, written out so a person can tell which one they mean; null if it is not that shape. */
export function dateReadings(example: string, locale: string): { dmy: string; mdy: string } | null {
  const m = /^\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})/.exec(example);
  if (!m) return null;
  const [a, b] = [Number(m[1]), Number(m[2])];
  const year = m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]);
  const write = (day: number, month: number) => {
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    return new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, day)));
  };
  const dmy = write(a, b);
  const mdy = write(b, a);
  return dmy && mdy ? { dmy, mdy } : null;
}

const SAMPLE_ORDER = ["date", "issue_date", "receipt", "number", "reference", "description", "party", "product", "counterparty", "money_in", "money_out", "amount", "total", "quantity", "balance"];

/** The few columns shown in the "what we found" table, in a sensible order, with the file's own column names. */
export function sampleColumns(fields: readonly FieldGuess[], max = 5): { name: string; label: string; header: string }[] {
  const chosen = fields.filter((f) => f.column && SAMPLE_ORDER.includes(f.name));
  chosen.sort((a, b) => SAMPLE_ORDER.indexOf(a.name) - SAMPLE_ORDER.indexOf(b.name));
  return chosen.slice(0, max).map((f) => ({ name: f.name, label: f.label, header: f.column as string }));
}

/** The fields shown first in the fix-it form: the ones that matter, then (on request) all the others. */
export const splitFields = (fields: readonly FieldGuess[]) => ({ main: fields.filter((f) => f.simple), more: fields.filter((f) => !f.simple) });

/** Quote a cell for a CSV file the person downloads. */
function cell(value: string): string {
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** The list of lines that were left out, as CSV text: line number, what is wrong, and what the line said. */
export function issuesCsv(preview: Pick<Preview, "issues" | "review_rows" | "headers">, labels: { line: string; problem: string }): string {
  const said = new Map(preview.review_rows.map((r) => [r.row, r.cells.filter(Boolean).join(" | ")]));
  const rows = preview.issues.map((i) => [String(i.row), i.message, said.get(i.row) ?? ""]);
  return [[labels.line, labels.problem, "Line text"], ...rows].map((r) => r.map(cell).join(",")).join("\r\n") + "\r\n";
}

/** Plain reasons to look closer, in the order they are shown. */
export const REASON_ORDER = ["wrong_kind", "missing", "picture", "dates", "problems", "unsure"] as const;

/** Which "what Ziira will now check" list fits what was stored. */
export function hintsFor(entities: readonly string[]): "statement" | "sales" | "invoices" | "stock" | "expenses" {
  if (entities.includes("payments")) return "statement";
  if (entities.includes("invoices")) return "invoices";
  if (entities.includes("stock_movements")) return "stock";
  if (entities.includes("expenses")) return "expenses";
  return "sales";
}
