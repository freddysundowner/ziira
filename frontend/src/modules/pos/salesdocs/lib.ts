/**
 * Pure helpers for the sales documents (quotations, orders, invoices, receipts, refunds): which actions a status allows,
 * what to send, and display-only figures. The backend owns the money; these never decide an amount.
 */
import type { BadgeTone } from "@/sdk";

/** Decimal string to whole cents, so display sums never drift (0.1 + 0.2). */
export const toCents = (value: string | null | undefined): number => {
  const n = Number(value);
  return value === "" || value == null || !Number.isFinite(n) ? 0 : Math.round(n * 100);
};

export const fromCents = (cents: number): string => (cents / 100).toFixed(2);

export const isPositive = (value: string | null | undefined): boolean => toCents(value) > 0;

// ---------------------------------------------------------------- statuses

const TONES: Record<string, BadgeTone> = {
  draft: "neutral", sent: "info", pending_approval: "warn", confirmed: "info", fulfilled: "ok", expired: "neutral", cancelled: "bad",
  issued: "info", part_paid: "warn", paid: "ok", overdue: "bad", posted: "ok", reversed: "bad",
};

/** The badge colour of a document status; unknown codes stay neutral. */
export const statusTone = (status: string): BadgeTone => TONES[status] ?? "neutral";

// ---------------------------------------------------------------- quotations and orders

export interface DocFacts { status: string; lines: { qty_delivered: string }[] }

export interface DocActions { edit: boolean; send: boolean; accept: boolean; submit: boolean; deliver: boolean; cancel: boolean }

const NONE: DocActions = { edit: false, send: false, accept: false, submit: false, deliver: false, cancel: false };

/** What may be done to a quotation in this status (the server has the last word). */
export function quotationActions(status: string): DocActions {
  if (status === "draft") return { ...NONE, edit: true, send: true, accept: true, cancel: true };
  if (status === "sent") return { ...NONE, accept: true, cancel: true };
  return NONE;
}

/** What may be done to a sales order: once goods have left, it can no longer be cancelled. */
export function orderActions(doc: DocFacts): DocActions {
  const delivered = doc.lines.some((l) => Number(l.qty_delivered) > 0);
  if (doc.status === "draft") return { ...NONE, edit: true, submit: true, cancel: true };
  if (doc.status === "pending_approval") return { ...NONE, cancel: true };
  if (doc.status === "confirmed") return { ...NONE, deliver: true, cancel: !delivered };
  return NONE;
}

/** What is left to deliver on an order line, as a plain decimal string (4 places at most). */
export function remainingToDeliver(line: { quantity: string; qty_delivered: string }): string {
  const left = Math.round((Number(line.quantity) - Number(line.qty_delivered)) * 10_000) / 10_000;
  return left > 0 ? String(left) : "0";
}

/** The delivery lines to send: those with a quantity above zero. Nothing chosen means "send nothing". */
export function deliveryLines(quantities: Record<string, string>): { order_line_id: string; quantity: string }[] {
  return Object.entries(quantities).filter(([, q]) => Number(q) > 0).map(([order_line_id, quantity]) => ({ order_line_id, quantity }));
}

/** Order lines where more is being delivered than is left. */
export function overDelivered(quantities: Record<string, string>, left: Record<string, string>): string[] {
  return Object.entries(quantities).filter(([id, q]) => Number(q) > Number(left[id] ?? 0)).map(([id]) => id);
}

// ---------------------------------------------------------------- the line editor

export interface EditLine { key: string; product_id: string; quantity: string; unit_price: string; discount: string }

export const blankLine = (): EditLine => ({ key: crypto.randomUUID(), product_id: "", quantity: "1", unit_price: "", discount: "" });

/** Lines with a product chosen: the only ones that are sent. */
export const filledLines = (lines: readonly EditLine[]): EditLine[] => lines.filter((l) => l.product_id);

/** Every filled line has a product and a quantity above zero, and at least one line is filled. */
export function linesValid(lines: readonly EditLine[]): boolean {
  const filled = filledLines(lines);
  return filled.length > 0 && filled.every((l) => Number(l.quantity) > 0);
}

/** A price or discount was typed, so the server will want a reason and the price.override permission. */
export const hasPriceChange = (l: EditLine): boolean => l.unit_price.trim() !== "" || Number(l.discount) > 0;

/** The lines in the shape the API wants. A blank price means "their price"; the reason is sent only with a change. */
export function lineBody(lines: readonly EditLine[], reasonId: string) {
  return filledLines(lines).map((l) => ({
    product_id: l.product_id, quantity: l.quantity, unit_price: l.unit_price.trim() === "" ? null : l.unit_price,
    discount: l.discount.trim() === "" ? "0" : l.discount, reason_code_id: hasPriceChange(l) && reasonId ? reasonId : null,
  }));
}

/**
 * A rough total while typing: quantity x price - discount per line, only when every filled line has a price typed.
 * Null otherwise (list prices are not known here). The saved document shows the server's figure.
 */
export function estimateTotal(lines: readonly EditLine[]): string | null {
  const filled = filledLines(lines);
  if (filled.length === 0 || filled.some((l) => l.unit_price.trim() === "")) return null;
  const cents = filled.reduce((sum, l) => sum + Math.round(Number(l.quantity || 0) * toCents(l.unit_price)) - toCents(l.discount), 0);
  return fromCents(cents);
}

/** A document's lines turned back into editable rows (to edit a draft). */
export function toEditLines(lines: { id: string; product_id: string; quantity: string; unit_price: string; discount_amount: string }[]): EditLine[] {
  return lines.map((l) => ({ key: l.id, product_id: l.product_id, quantity: String(Number(l.quantity)), unit_price: l.unit_price, discount: Number(l.discount_amount) > 0 ? l.discount_amount : "" }));
}

// ---------------------------------------------------------------- invoices

export interface InvoiceFacts {
  kind: string; status: string; total: string; amount_paid: string; credited: string; due_date: string;
}

/** What is still owed on an invoice (display only, from the invoice's own figures). */
export const outstanding = (i: Pick<InvoiceFacts, "total" | "amount_paid" | "credited" | "status">): string =>
  i.status === "cancelled" ? "0.00" : fromCents(Math.max(0, toCents(i.total) - toCents(i.amount_paid) - toCents(i.credited)));

const OPEN = ["issued", "part_paid"];

/** Unpaid past its due date. `today` is a YYYY-MM-DD date. */
export const isOverdue = (i: Pick<InvoiceFacts, "status" | "due_date" | "total" | "amount_paid" | "credited">, today: string): boolean =>
  OPEN.includes(i.status) && i.due_date < today && isPositive(outstanding({ ...i, status: i.status }));

/** The status shown for an invoice: "overdue" when it is open and late. */
export const invoiceDisplayStatus = (i: Pick<InvoiceFacts, "status" | "due_date" | "total" | "amount_paid" | "credited">, today: string): string =>
  isOverdue(i, today) ? "overdue" : i.status;

export interface InvoiceActions { cancel: boolean; giveBack: boolean; receive: boolean }

/** Cancel only an untouched invoice for goods (not a till credit sale or an opening balance); returns need goods; payment needs something owed. */
export function invoiceActions(i: InvoiceFacts): InvoiceActions {
  const goods = i.kind === "invoice";
  return {
    cancel: goods && i.status === "issued" && !isPositive(i.amount_paid) && !isPositive(i.credited),
    giveBack: goods && i.status !== "cancelled",
    receive: OPEN.includes(i.status) && isPositive(outstanding(i)),
  };
}

/** Refund methods the server accepts for an invoice: a credit note only while something is owed (up to what is owed), money back only once it is paid. */
export function returnMethods(i: Pick<InvoiceFacts, "total" | "amount_paid" | "credited" | "status">): ("credit_note" | "cash" | "mobile_money" | "exchange")[] {
  return isPositive(outstanding(i)) ? ["credit_note", "exchange"] : ["cash", "mobile_money", "exchange"];
}

// ---------------------------------------------------------------- receipts and refunds

export interface ReceiptActions { reverse: boolean; refund: boolean; applyCredit: boolean }

/** A payment can be reversed until part of it is refunded; money held on account can be used on invoices or given back. */
export function receiptActions(r: { status: string; unallocated: string; refunded: string }): ReceiptActions {
  const posted = r.status === "posted";
  const held = posted && isPositive(r.unallocated);
  return { reverse: posted && !isPositive(r.refunded), refund: held, applyCredit: held };
}

// ---------------------------------------------------------------- offline rejections

export interface RejectedSale {
  number: string | null; at: string | null; customerId: string | null;
  lines: { productId: string; quantity: string; unitPrice: string | null; discount: string }[];
  payments: { method: string; amount: string; reference: string | null }[];
}

const text = (v: unknown): string | null => (typeof v === "string" ? v : typeof v === "number" ? String(v) : null);

/** Reads the sale a till sent (kept whole by the server) into plain parts; anything missing or odd is left out, never guessed. */
export function readRejectedSale(payload: Record<string, unknown>): RejectedSale {
  const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => typeof x === "object" && x !== null) : []);
  return {
    number: text(payload.number), at: text(payload.at), customerId: text(payload.customer_id),
    lines: list(payload.lines).map((l) => ({ productId: text(l.product_id) ?? "", quantity: text(l.quantity) ?? "0", unitPrice: text(l.unit_price), discount: text(l.discount) ?? "0" })),
    payments: list(payload.payments).map((p) => ({ method: text(p.method) ?? "", amount: text(p.amount) ?? "0", reference: text(p.external_ref) })),
  };
}

/** What the till charged for a rejected sale's lines, when every line carried its price. Null when some did not. */
export function rejectedSaleTotal(sale: RejectedSale): string | null {
  if (sale.lines.length === 0 || sale.lines.some((l) => l.unitPrice == null)) return null;
  return fromCents(sale.lines.reduce((sum, l) => sum + Math.round(Number(l.quantity) * toCents(l.unitPrice)) - toCents(l.discount), 0));
}

/** The day before a YYYY-MM-DD date (an invoice is overdue when it was due before today). */
export function dayBefore(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}
