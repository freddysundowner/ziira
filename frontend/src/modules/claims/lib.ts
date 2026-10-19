/** Pure helpers of the Claims screens: tones, estimate-editor rows and their checks, amounts. No React, no network. */
import type { BadgeTone } from "@/sdk";

import type { EstimateLine, LineKind } from "./types";

export function statusTone(status: string): BadgeTone {
  switch (status) {
    case "settled": return "ok";
    case "closed": return "neutral";
    case "invoiced": return "info";
    case "completed": return "brand";
    case "authorised": return "ok";
    case "open": return "warn";
    default: return "neutral";
  }
}

export function answerTone(state: string): BadgeTone {
  switch (state) {
    case "approved": return "ok";
    case "countered": return "warn";
    case "rejected": return "bad";
    case "needs_information": return "info";
    default: return "neutral";
  }
}

export function waitingTone(w: string | null | undefined): BadgeTone {
  return w === "us" ? "bad" : w === "customer" ? "warn" : w === "payer" ? "info" : "neutral";
}

/** Amounts arrive as decimal strings: compare and add them in cents so no float error shows. */
export const cents = (value: string | number | null | undefined): number => Math.round(Number(value ?? 0) * 100);
export const fromCents = (value: number): string => (value / 100).toFixed(2);
export const sumAmounts = (values: readonly (string | number | null | undefined)[]): string => fromCents(values.reduce<number>((n, v) => n + cents(v), 0));

/** Quantity times price to the cent, as the server does it. */
export function lineTotal(quantity: string, price: string): string {
  const q = Number(quantity), p = Number(price);
  if (!Number.isFinite(q) || !Number.isFinite(p) || q <= 0 || p < 0) return "0.00";
  return (Math.round(q * p * 100) / 100).toFixed(2);
}

/** One row of the estimate editor. `locked` rows were settled by the payer in an earlier version and cannot change. */
export interface EditorRow {
  key: string;
  id: string | null;
  kind: LineKind;
  description: string;
  quantity: string;
  unitPrice: string;
  workType: string;
  partClass: string;
  locked: boolean;
}

let counter = 0;
export const newKey = () => `row-${++counter}`;

export const blankRow = (kind: LineKind = "labour"): EditorRow => ({ key: newKey(), id: null, kind, description: "", quantity: "1", unitPrice: "", workType: "", partClass: "", locked: false });

export function rowsFromLines(lines: readonly EstimateLine[]): EditorRow[] {
  return lines.map((l) => ({
    key: l.id, id: l.id, kind: l.kind as LineKind, description: l.description, quantity: String(Number(l.quantity)),
    unitPrice: String(Number(l.unit_price)), workType: l.work_type ?? "", partClass: l.part_class ?? "", locked: l.locked,
  }));
}

export type RowProblem = "description" | "quantity" | "price";

/** What is wrong with a row. Labour and paint may leave the price blank (the payer's rate is used); other kinds need one. */
export function rowProblems(row: EditorRow): RowProblem[] {
  const found: RowProblem[] = [];
  if (!row.description.trim()) found.push("description");
  const q = Number(row.quantity);
  if (!row.quantity.trim() || !Number.isFinite(q) || q <= 0) found.push("quantity");
  const blankAllowed = row.kind === "labour" || row.kind === "paint";
  const p = Number(row.unitPrice);
  if (row.unitPrice.trim() ? !Number.isFinite(p) || p < 0 : !blankAllowed) found.push("price");
  return found;
}

export const editableRows = (rows: readonly EditorRow[]) => rows.filter((r) => !r.locked);
export const hasProblems = (rows: readonly EditorRow[]) => editableRows(rows).some((r) => rowProblems(r).length > 0);

/** The lines to send: settled rows are left to the server, the others in full (an existing row keeps its id and its history). */
export function toLineBody(rows: readonly EditorRow[]) {
  return editableRows(rows).map((r) => ({
    line_id: r.id, kind: r.kind, description: r.description.trim(), quantity: r.quantity.trim(),
    unit_price: r.unitPrice.trim() === "" ? null : r.unitPrice.trim(),
    work_type: r.kind === "labour" && r.workType.trim() ? r.workType.trim() : null,
    part_class: r.kind === "parts" && r.partClass ? (r.partClass as "genuine" | "aftermarket" | "used") : null,
  }));
}

export function rowsTotal(rows: readonly EditorRow[], settled: readonly EstimateLine[] = []): string {
  const fresh = editableRows(rows).map((r) => (r.unitPrice.trim() ? lineTotal(r.quantity, r.unitPrice) : "0"));
  return sumAmounts([...fresh, ...settled.map((l) => l.asked_total)]);
}

/** A line that can still be answered on an estimate: the payer has not decided it and it is not settled from before. */
export const canAnswer = (l: EstimateLine) => !l.locked && (l.payer_state === "pending" || l.payer_state === "needs_information");

/** True when every line of the estimate is settled one way or the other (nothing waits for anyone). */
export const nothingWaiting = (lines: readonly EstimateLine[]) => lines.every((l) => l.waiting_on === null);

export function daysSince(iso: string | null | undefined, now = new Date()): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  return Number.isFinite(then) ? Math.max(0, Math.floor((now.getTime() - then) / 86_400_000)) : null;
}

/** The answer a staff member typed for one line, ready to send; null while the row is incomplete. */
export interface AnswerRow { lineId: string; state: string; amount: string; reason: string }
export function answerProblem(row: AnswerRow, asked: string): string | null {
  if (!row.state) return "state";
  if (row.state === "countered") {
    const a = cents(row.amount);
    if (!row.amount.trim() || a < 0 || a >= cents(asked)) return "amount";
  }
  if (row.state === "rejected" && !row.reason.trim()) return "reason";
  return null;
}
export function toAnswers(rows: readonly AnswerRow[]) {
  return rows.filter((r) => r.state).map((r) => ({
    line_id: r.lineId, state: r.state as "approved" | "countered" | "rejected" | "needs_information",
    amount: r.state === "countered" ? r.amount.trim() : null, reason: r.reason.trim() || null,
  }));
}
