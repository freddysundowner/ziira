/**
 * A sale made without a connection, worked out on the device: the request to send later and the receipt to print now.
 * The server recalculates everything when it receives the sale; its figures are the ones that count. These follow the
 * same rules (prices include tax, tax inside = gross x rate / (100 + rate), rounded half up) so the paper is right.
 */
import { getDisplayTimeZone, type Schemas } from "@/sdk";

import { type CartLine, num, type PayLeg } from "../cart";
import type { OutboxEntry, SaleOp } from "./types";

/** Whole cents from a decimal amount typed or sent as text. */
export const toCents = (value: string | number): number => Math.round((Number(value) + Number.EPSILON) * 100);
export const fromCents = (cents: number): string => (cents / 100).toFixed(2);

/** Quantity x unit price in cents, half up. Quantity has up to 4 decimals. */
function lineCents(quantity: string, price: string): number {
  const q = Math.round(Number(quantity) * 10_000);
  return Math.floor((q * toCents(price) * 2 + 10_000) / 20_000);
}

/** The tax inside a tax-inclusive amount: gross x rate / (100 + rate), half up. */
export function taxInside(grossCents: number, rate: string): number {
  const bp = Math.round(Number(rate) * 100);
  if (grossCents <= 0 || bp <= 0) return 0;
  const den = 10_000 + bp;
  return Math.floor((grossCents * bp * 2 + den) / (2 * den));
}

export interface PricedLine {
  line: CartLine;
  beforeCents: number;
  discountCents: number;
  grossCents: number;
  taxCents: number;
  rate: string;
}

export function priceLines(lines: CartLine[]): PricedLine[] {
  return lines.map((line) => {
    const beforeCents = lineCents(line.quantity, line.price);
    const discountCents = Math.min(toCents(line.discount || "0"), beforeCents);
    const grossCents = beforeCents - discountCents;
    const rate = line.vatRate || "0";
    return { line, beforeCents, discountCents, grossCents, taxCents: taxInside(grossCents, rate), rate };
  });
}

export interface Labels {
  title: string;
  provisional: string;
  date: string;
  servedBy: string;
  customer: string;
  subtotal: string;
  discount: string;
  total: string;
}

export interface OfflineSaleInput {
  localId: string;
  tillId: string;
  branchId: string;
  userId: string;
  number: string;
  madeAt: number;
  offsetMs: number;
  currency: string;
  lines: CartLine[];
  legs: PayLeg[];
  customerId: string;
  customerName: string;
  cashierName: string;
  header: string[];
  footer: string[];
  labels: Labels;
}

/** A moment as "YYYY-MM-DD HH:MM" on the company's clock (the device's until the company is known), like the server's receipt. */
export const stamp = (ms: number): string => {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: getDisplayTimeZone(), year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
};

/** The sale as the sync endpoint wants it. Every line carries the price the customer was charged: the list may change before the sale is sent. */
export function toOfflineOp(input: OfflineSaleInput): SaleOp {
  return {
    type: "sale",
    local_id: input.localId,
    till_session_id: input.tillId,
    at: new Date(input.madeAt + input.offsetMs).toISOString(),
    lines: input.lines.map((l) => ({
      product_id: l.productId,
      quantity: l.quantity,
      unit_price: l.price,
      discount: l.discount || "0",
      ...(l.reasonId ? { reason_code_id: l.reasonId } : {}),
      ...((l.reference ?? "").trim() ? { reference: (l.reference ?? "").trim() } : {}),
    })),
    payments: input.legs.filter((l) => num(l.amount) > 0).map((l) => ({
      method: l.method,
      amount: l.amount,
      ...(l.ref.trim() ? { external_ref: l.ref.trim() } : {}),
      ...(l.method === "mobile_money" && l.accountId ? { payment_account_id: l.accountId } : {}),
    })),
    ...(input.customerId ? { customer_id: input.customerId } : {}),
  };
}

/** The receipt in the shape of the server's, marked as provisional. */
export function buildReceipt(input: OfflineSaleInput): Schemas["PrintOut"] {
  const priced = priceLines(input.lines);
  const subtotal = priced.reduce((s, p) => s + p.beforeCents, 0);
  const discount = priced.reduce((s, p) => s + p.discountCents, 0);
  const total = subtotal - discount;
  const other = input.legs.filter((l) => l.method !== "cash" && num(l.amount) > 0).reduce((s, l) => s + toCents(l.amount), 0);
  const cash = input.legs.filter((l) => l.method === "cash").reduce((s, l) => s + toCents(l.amount || "0"), 0);
  const cashApplied = Math.min(cash, Math.max(0, total - other));

  const byRate = new Map<string, { gross: number; tax: number }>();
  for (const p of priced) {
    const row = byRate.get(p.rate) ?? { gross: 0, tax: 0 };
    byRate.set(p.rate, { gross: row.gross + p.grossCents, tax: row.tax + p.taxCents });
  }
  const totals = [{ label: input.labels.subtotal, amount: fromCents(subtotal) }];
  if (discount > 0) totals.push({ label: input.labels.discount, amount: fromCents(-discount) });
  totals.push({ label: input.labels.total, amount: fromCents(total) });
  const meta = [[input.labels.date, stamp(input.madeAt)], [input.labels.servedBy, input.cashierName]];
  if (input.customerName) meta.push([input.labels.customer, input.customerName]);
  const payments = input.legs.filter((l) => l.method !== "cash" && num(l.amount) > 0).map((l) => ({ label: l.method.toUpperCase(), amount: fromCents(toCents(l.amount)) }));
  if (cashApplied > 0) payments.unshift({ label: "CASH", amount: fromCents(cashApplied) });

  return {
    title: input.labels.title,
    number: input.number,
    header: input.header,
    meta: meta.filter((m) => m[1]),
    lines: priced.map((p) => ({ description: p.line.name, quantity: p.line.quantity, unit_price: p.line.price, amount: fromCents(p.grossCents) })),
    vat: [...byRate.entries()].filter(([rate]) => Number(rate) > 0).sort((a, b) => Number(a[0]) - Number(b[0]))
      .map(([rate, v]) => ({ rate, net: fromCents(v.gross - v.tax), tax: fromCents(v.tax) })),
    totals,
    payments,
    notes: [input.labels.provisional],
    footer: input.footer,
    is_copy: false,
  };
}

export interface BuiltSale {
  op: SaleOp;
  receipt: Schemas["PrintOut"];
  total: string;
  change: string;
  lines: OutboxEntry["lines"];
}

/** Everything the outbox keeps about a sale. */
export function buildOfflineSale(input: OfflineSaleInput): BuiltSale {
  const priced = priceLines(input.lines);
  const total = priced.reduce((s, p) => s + p.grossCents, 0);
  const handed = input.legs.reduce((s, l) => s + toCents(l.amount || "0"), 0);
  const other = input.legs.filter((l) => l.method !== "cash").reduce((s, l) => s + toCents(l.amount || "0"), 0);
  const change = Math.max(0, handed - other - Math.max(0, total - other));
  return {
    op: toOfflineOp(input),
    receipt: buildReceipt(input),
    total: fromCents(total),
    change: fromCents(change),
    lines: priced.map((p) => ({ sku: p.line.sku, name: p.line.name, quantity: p.line.quantity, amount: fromCents(p.grossCents) })),
  };
}
