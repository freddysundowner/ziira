/** Pure helpers for the purchasing screens: statuses, line previews and request bodies. */
import type { BillSummary, Order } from "./types";

export const ORDER_STATUSES = ["draft", "pending_approval", "approved", "sent", "part_received", "received", "closed", "cancelled"] as const;
export const BILL_STATUSES = ["draft", "pending_approval", "posted", "part_paid", "paid", "cancelled", "reversed"] as const;
export const SUPPLIER_STATUSES = ["active", "on_hold", "inactive"] as const;
export const PAY_METHODS = ["cash", "mobile_money", "bank", "card", "cheque", "other"] as const;
export const AGE_BUCKETS = ["not_due", "1_30", "31_60", "61_90", "over_90"] as const;

/** A bill the business still owes money on. */
export const isOpenBill = (status: string): boolean => status === "posted" || status === "part_paid";

/** Money still to pay on a bill. Display only: the server checks every payment against its own figures. */
export function amountDue(bill: Pick<BillSummary, "total" | "amount_paid" | "credited">): string {
  return Math.max(Number(bill.total) - Number(bill.amount_paid) - Number(bill.credited), 0).toFixed(2);
}

export const isOverdue = (bill: Pick<BillSummary, "status" | "due_date">, today: string): boolean => isOpenBill(bill.status) && bill.due_date < today;

/** Rough total of the lines being typed, before VAT. The server's totals replace it after saving. */
export function previewSubtotal(lines: { quantity: string; unit_cost: string }[]): string {
  const cents = lines.reduce((sum, l) => sum + Math.round((Number(l.quantity) || 0) * (Number(l.unit_cost) || 0) * 100), 0);
  return (cents / 100).toFixed(2);
}

/** What is left of a quantity after some of it has been used (received, credited), never below zero. */
export function remaining(total: string, used: string): string {
  return String(Math.max(Math.round((Number(total) - Number(used)) * 1e4) / 1e4, 0));
}

/** Quantity still expected on an order line. */
export const stillToReceive = (line: { quantity: string; qty_received: string }): string => remaining(line.quantity, line.qty_received);

export const canReceive = (order: Pick<Order, "status">): boolean => ["approved", "sent", "part_received"].includes(order.status);

/** True when the text is a positive number. */
export const isPositive = (value: string): boolean => Number(value) > 0;

/** A date input (YYYY-MM-DD) as the moment the server expects, or undefined for "today, now". */
export function dayToTimestamp(day: string, today: string): string | undefined {
  return !day || day === today ? undefined : new Date(`${day}T12:00:00`).toISOString();
}

export interface PayableRow { supplier_id: string; supplier: string; total: string; [bucket: string]: string }

const toCents = (value: string): number => Math.round((Number(value) || 0) * 100);

/**
 * Spread one payment over bills, oldest due date first, never more than each bill's balance.
 * Only a suggestion for the form: the server checks every payment against its own figures.
 */
export function allocateOldestFirst(total: string, bills: { id: string; due_date: string; due: string }[]): Record<string, string> {
  let left = toCents(total);
  const out: Record<string, string> = {};
  for (const bill of [...bills].sort((a, b) => a.due_date.localeCompare(b.due_date))) {
    const part = Math.min(left, toCents(bill.due));
    if (part <= 0) continue;
    out[bill.id] = (part / 100).toFixed(2);
    left -= part;
  }
  return out;
}

/** Sum of typed amounts, for the confirmation text. */
export const sumAmounts = (values: string[]): string => (values.reduce((s, v) => s + toCents(v), 0) / 100).toFixed(2);

/** A date (YYYY-MM-DD) some days later. */
export function addDays(day: string, days: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
