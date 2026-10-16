/**
 * Invoice lines as the form holds them (text), a preview of each line's amount, and the request the API takes.
 * The preview is exact (whole-number arithmetic on the digits, rounded half up to two decimals like the server) and is
 * only a preview: after saving, the server's totals, tax lines and numbers are what count.
 */

export interface LineDraft {
  description: string;
  quantity: string;
  unit_amount: string;
}

export const emptyLine = (): LineDraft => ({ description: "", quantity: "1", unit_amount: "" });

/** A decimal string as a whole number of 10^-scale units; null when it is not a number or has too many decimals. */
function scaled(value: string, scale: number): bigint | null {
  const m = /^(-?)(\d*)(?:\.(\d*))?$/.exec(value.trim());
  if (!m || (m[2] === "" && !m[3])) return null;
  const fraction = m[3] ?? "";
  if (fraction.length > scale) return null;
  const n = BigInt((m[2] || "0") + fraction.padEnd(scale, "0"));
  return m[1] ? -n : n;
}

function format(n: bigint): string {
  const negative = n < 0n;
  const digits = (negative ? -n : n).toString().padStart(3, "0");
  return `${negative ? "-" : ""}${digits.slice(0, -2)}.${digits.slice(-2)}`;
}

/** quantity x unit amount, rounded half up to two decimals; null while either is not a valid number. */
export function lineAmount(quantity: string, unitAmount: string): string | null {
  const q = scaled(quantity, 3), u = scaled(unitAmount, 2);
  if (q === null || u === null) return null;
  const product = q * u;                                     // three plus two decimals
  const rounded = ((product < 0n ? -product : product) + 500n) / 1000n;
  return format(product < 0n ? -rounded : rounded);
}

/** The sum of line amounts that are valid so far. */
export function previewSubtotal(lines: LineDraft[]): string {
  let sum = 0n;
  for (const line of lines) {
    const amount = lineAmount(line.quantity, line.unit_amount);
    if (amount !== null && line.description.trim()) sum += scaled(amount, 2) ?? 0n;
  }
  return format(sum);
}

export interface InvoiceDraft {
  tenant_code: string;
  licence_id: string;
  currency: string;
  lines: LineDraft[];
  tax_inclusive: boolean;
  notes: string;
  due_date: string;
  issue: boolean;
}

/** Translation keys (under "billing.invoiceForm.problems") of what is wrong with the form; empty when it can be sent. */
export function invoiceProblems(draft: InvoiceDraft): string[] {
  const problems: string[] = [];
  if (!draft.tenant_code.trim() && !draft.licence_id.trim()) problems.push("target");
  if (draft.currency.trim() && !/^[A-Za-z]{3}$/.test(draft.currency.trim())) problems.push("currency");
  const filled = draft.lines.filter((l) => l.description.trim() || l.unit_amount.trim());
  if (filled.length === 0) problems.push("noLines");
  else if (filled.some((l) => !l.description.trim() || lineAmount(l.quantity, l.unit_amount) === null || Number(l.quantity) <= 0)) problems.push("badLine");
  return problems;
}

/** The API's request for a form that has no problems. */
export function toInvoiceIn(draft: InvoiceDraft) {
  return {
    tenant_code: draft.tenant_code.trim() || null,
    licence_id: draft.tenant_code.trim() ? null : draft.licence_id.trim() || null,
    currency: draft.currency.trim() ? draft.currency.trim().toUpperCase() : null,
    lines: draft.lines
      .filter((l) => l.description.trim() || l.unit_amount.trim())
      .map((l) => ({ description: l.description.trim(), quantity: l.quantity.trim(), unit_amount: l.unit_amount.trim() })),
    tax_inclusive: draft.tax_inclusive,
    notes: draft.notes.trim(),
    due_date: draft.due_date || null,
    issue: draft.issue,
  };
}
