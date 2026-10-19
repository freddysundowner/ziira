import type { BadgeTone } from "@/sdk";

import type { Checkout, Offer } from "../types";

/** Pure rules of the front desk board and the checkout screen (no network, no React). */

// ------------------------------------------------------------------ board
export type PersonState = "free" | "busy" | "processing" | "off";

export const STATE_TONE: Record<PersonState, BadgeTone> = { free: "ok", busy: "brand", processing: "info", off: "neutral" };

/** The offers shown as one-tap chips: active, bookable by a person (not group classes), first `limit` in the list's order. */
export function quickOffers(offers: readonly Offer[], limit = 6): Offer[] {
  return offers.filter((o) => o.is_active && o.kind !== "class").slice(0, limit);
}

export type StepName = "confirm" | "check-in" | "start" | "finish";

/** The next step an appointment can take at the desk, by its status; null when none. */
export function nextStep(status: string): StepName | null {
  switch (status) {
    case "requested": return "confirm";
    case "confirmed": return "check-in";
    case "checked_in": return "start";
    case "in_service": return "finish";
    default: return null;
  }
}

// ------------------------------------------------------------------ amounts as exact text
/** A decimal text as a whole number of ten-thousandths (exact, no floating point); null when it is not a plain amount. */
export function toUnits(text: string): bigint | null {
  const t = text.trim().replace(/,/g, ".");
  const m = /^(\d*)(?:\.(\d*))?$/.exec(t);
  if (!m || (m[1] === "" && (m[2] ?? "") === "")) return null;
  const frac = ((m[2] ?? "") + "0000").slice(0, 4);
  return BigInt(m[1] || "0") * 10000n + BigInt(frac);
}

/** True when the text is an amount above zero. */
export function isPositive(text: string): boolean {
  const u = toUnits(text);
  return u !== null && u > 0n;
}

/** What to send for an amount box: digits only, "0" when empty, no dangling point. */
export function cleanAmount(text: string): string {
  const t = text.trim().replace(/,/g, ".").replace(/\.$/, "");
  return t === "" || t === "." ? "0" : t;
}

export type Settlement = "exact" | "short" | "over";

/**
 * Do the payments entered cover the total? Only a comparison for the "are you sure" step; the server does the sums and
 * has the last word (it refuses an over-payment and keeps a short one as owing).
 */
export function settlement(total: string, parts: readonly string[]): Settlement {
  const owed = toUnits(total) ?? 0n;
  const paid = parts.reduce<bigint>((sum, p) => sum + (toUnits(p) ?? 0n), 0n);
  return paid === owed ? "exact" : paid < owed ? "short" : "over";
}

// ------------------------------------------------------------------ the draft of a bill
export interface LineDraft {
  key: string;
  kind: "service" | "product" | "fee";
  appointment_id: string;
  offer_id: string;
  product_id: string;
  fee_id: string;
  description: string;
  quantity: string;
  /** Empty: the server fills in the list price on the next save. */
  unit_price: string;
  discount: string;
  resource_id: string;
  variant: string;
  use_credit: boolean;
}

export interface DraftState {
  lines: LineDraft[];
  discount_kind: "amount" | "percent";
  discount_value: string;
  discount_reason_id: string;
  discount_note: string;
  note: string;
  payer_customer_id: string;
  copay_amount: string;
  preauth_ref: string;
}

let counter = 0;
export const newKey = (): string => `n${Date.now().toString(36)}${(counter++).toString(36)}`;

const num = (v: string | number | null | undefined, fallback = ""): string => (v === null || v === undefined ? fallback : String(v));

/** The editable draft shown on screen, from what the server holds. */
export function draftFromCheckout(co: Checkout): DraftState {
  return {
    lines: co.lines.map((l) => ({
      key: l.id, kind: l.kind as LineDraft["kind"], appointment_id: l.appointment_id ?? "", offer_id: l.offer_id ?? "", product_id: l.product_id ?? "",
      fee_id: l.fee_id ?? "", description: l.description, quantity: num(l.quantity, "1"), unit_price: num(l.unit_price), discount: num(l.discount, "0"),
      resource_id: l.resource_id ?? "", variant: l.variant ?? "", use_credit: Number(l.credit_quantity) > 0,
    })),
    discount_kind: co.discount_kind === "percent" ? "percent" : "amount",
    discount_value: num(co.discount_value, "0"),
    discount_reason_id: co.discount_reason_id ?? "",
    discount_note: co.discount_note ?? "",
    note: co.note ?? "",
    payer_customer_id: co.payer_customer_id ?? "",
    copay_amount: num(co.copay_amount),
    preauth_ref: co.preauth_ref ?? "",
  };
}

export function serviceLine(offer: { id: string; name: string }, resourceId = ""): LineDraft {
  return { key: newKey(), kind: "service", appointment_id: "", offer_id: offer.id, product_id: "", fee_id: "", description: offer.name, quantity: "1", unit_price: "", discount: "0", resource_id: resourceId, variant: "", use_credit: false };
}

export function productLine(item: { id: string; name: string; price?: string | number | null }): LineDraft {
  return { key: newKey(), kind: "product", appointment_id: "", offer_id: "", product_id: item.id, fee_id: "", description: item.name, quantity: "1", unit_price: num(item.price), discount: "0", resource_id: "", variant: "", use_credit: false };
}

const orNull = (s: string): string | null => (s.trim() === "" ? null : s.trim());

/** The request body that saves a draft. */
export function draftBody(d: DraftState) {
  const payer = orNull(d.payer_customer_id);
  return {
    lines: d.lines.map((l) => ({
      kind: l.kind, quantity: cleanAmount(l.quantity) === "0" ? "1" : cleanAmount(l.quantity), appointment_id: orNull(l.appointment_id), offer_id: orNull(l.offer_id),
      product_id: orNull(l.product_id), fee_id: orNull(l.fee_id), description: orNull(l.description),
      unit_price: l.unit_price.trim() === "" ? null : cleanAmount(l.unit_price), discount: cleanAmount(l.discount),
      resource_id: orNull(l.resource_id), variant: orNull(l.variant), use_credit: l.use_credit,
    })),
    discount_kind: d.discount_kind,
    discount_value: cleanAmount(d.discount_value),
    discount_reason_id: orNull(d.discount_reason_id),
    discount_note: orNull(d.discount_note),
    note: orNull(d.note),
    payer_customer_id: payer,
    copay_amount: payer && d.copay_amount.trim() !== "" ? cleanAmount(d.copay_amount) : null,
    preauth_ref: payer ? orNull(d.preauth_ref) : null,
  };
}

/** A discount, on the order or on any line, needs a reason. */
export function hasDiscount(d: DraftState): boolean {
  return isPositive(d.discount_value) || d.lines.some((l) => isPositive(l.discount));
}

/** Staff on the lines of the bill, once each, in order (the default people for tips). */
export function staffOnLines(lines: readonly LineDraft[]): string[] {
  const seen: string[] = [];
  for (const l of lines) if (l.resource_id && !seen.includes(l.resource_id)) seen.push(l.resource_id);
  return seen;
}

/** After a save: fill the price and name the server worked out into lines that had none (matched by position). */
export function fillFromServer(lines: readonly LineDraft[], co: Checkout): LineDraft[] {
  if (co.lines.length !== lines.length) return [...lines];
  return lines.map((l, i) => {
    const s = co.lines[i];
    if (!s) return l;
    return { ...l, unit_price: l.unit_price.trim() === "" ? num(s.unit_price) : l.unit_price, description: l.description || s.description };
  });
}
