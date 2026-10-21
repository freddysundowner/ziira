import type { BadgeTone, Schemas } from "@/sdk";

export type MyPlan = Schemas["MyPlan"];
export type PublicPlan = Schemas["PublicPlan"];
export type PublicPrice = Schemas["PublicPrice"];
export type Invoice = Schemas["MyInvoice"];
export type Licence = Schemas["LicenceInfo"];

export type UsageLevel = "ok" | "near" | "over";

/** How full a limit is: the percentage (null when unlimited) and whether to warn (80% or more) or flag it as over. */
export function usageLevel(used: number, limit: number | null | undefined): { pct: number | null; level: UsageLevel } {
  if (limit === null || limit === undefined) return { pct: null, level: "ok" };
  if (limit <= 0) return { pct: used > 0 ? 100 : 0, level: used > 0 ? "over" : "ok" };
  const pct = Math.round((used / limit) * 100);
  return { pct, level: used > limit ? "over" : pct >= 80 ? "near" : "ok" };
}

/** Colour of a subscription status. */
export function statusTone(status: string): BadgeTone {
  switch (status) {
    case "active": return "ok";
    case "trialing": return "info";
    case "past_due": case "grace": return "warn";
    case "suspended": case "cancelled": case "expired": return "bad";
    default: return "neutral";
  }
}

/** Colour of a licence state (self-hosted copies). */
export function licenceTone(status: string): BadgeTone {
  switch (status) {
    case "valid": return "ok";
    case "grace": return "warn";
    case "expired": case "revoked": case "wrong_instance": case "clock_rollback": return "bad";
    default: return "neutral";
  }
}

/** Colour of an invoice status; an unpaid issued invoice is the one that matters. */
export function invoiceTone(status: string): BadgeTone {
  switch (status) {
    case "paid": return "ok";
    case "issued": case "partial": return "warn";
    case "void": case "uncollectible": return "bad";
    default: return "neutral";
  }
}

/** An invoice the business still has to pay. */
export const isOwed = (i: Pick<Invoice, "status" | "balance">): boolean => (i.status === "issued" || i.status === "partial") && Number(i.balance) > 0;

/** The banner levels the API sends, as the colour of an Alert. */
export function bannerTone(level: string): "info" | "warn" | "bad" {
  return level === "blocked" ? "bad" : level === "warning" ? "warn" : "info";
}

/** The currency to show a plan's prices in: the business's own when the plan prices it, otherwise the plan's first. */
export function priceCurrency(plan: Pick<PublicPlan, "prices">, preferred: string | null | undefined): string | null {
  const wanted = (preferred ?? "").toUpperCase();
  const codes = plan.prices.map((p) => p.currency.trim().toUpperCase());
  if (wanted && codes.includes(wanted)) return wanted;
  return codes[0] ?? null;
}

/** The billing intervals a plan offers in a currency, month before year. */
export function intervalsFor(plan: Pick<PublicPlan, "prices">, currency: string | null): string[] {
  const order = ["month", "year", "one_time"];
  const found = new Set(plan.prices.filter((p) => p.currency.trim().toUpperCase() === currency).map((p) => p.interval));
  return order.filter((i) => found.has(i));
}

/** The price for a currency and interval, or the first interval the plan offers in that currency when the one asked for is not offered. */
export function pickPrice(plan: Pick<PublicPlan, "prices">, currency: string | null, interval: string): PublicPrice | null {
  const inCurrency = plan.prices.filter((p) => p.currency.trim().toUpperCase() === currency);
  return inCurrency.find((p) => p.interval === interval) ?? inCurrency[0] ?? null;
}

/** What is sent when the owner asks for another plan; blanks are left out. */
export function changeRequestBody(plan: string, price: Pick<PublicPrice, "currency" | "interval"> | null, coupon: string, note: string): Schemas["ChangeRequestIn"] {
  return {
    plan_code: plan,
    ...(price ? { interval: price.interval, currency: price.currency.trim().toUpperCase() } : {}),
    ...(coupon.trim() ? { coupon_code: coupon.trim() } : {}),
    note: note.trim(),
  };
}

/** The owed amounts as "KES 1,200.00 · USD 5.00" parts, one per currency, skipping zero. */
export function owedEntries(owed: Record<string, string>): [string, string][] {
  return Object.entries(owed).filter(([, v]) => Number(v) > 0);
}
export const PLAN_KEY = ["billing-plan"];
export const STATUS_KEY = ["billing-status"];
export const ADDONS_KEY = ["billing-addons"];
export const CATALOG_KEY = ["units-catalog"];

export type PayOptions = Schemas["PayOptions"];
export type PayOption = Schemas["PayOption"];
export type Attempt = Schemas["PaymentAttemptOut"];

/** How often the status of an open payment is read from our own API, and how long the app waits before it says "not heard back". */
export const POLL_MS = 3000;
export const WAIT_SECONDS = 120;

/** Seconds left of the wait, counting from when the payment was started (never negative). */
export function secondsLeft(startedAt: number, now: number, wait = WAIT_SECONDS): number {
  return Math.max(0, Math.ceil(wait - (now - startedAt) / 1000));
}

export type PayPhase = "waiting" | "paid" | "failed" | "mismatch" | "timeout" | "expired";

/** What the owner is told about an attempt: open ones wait (a prompt on the phone has a time limit, a provider page does not). */
export function payPhase(attempt: Pick<Attempt, "status" | "flow">, left: number): PayPhase {
  switch (attempt.status) {
    case "completed": return "paid";
    case "failed": return "failed";
    case "mismatch": return "mismatch";
    case "expired": return "expired";
    default: return attempt.flow === "prompt" && left === 0 ? "timeout" : "waiting";
  }
}

/** The first issued invoice with something owing (what the "Pay" button is about), oldest due date first. An add-on waiting at the checkout is not a debt. */
export function firstOwed(invoices: readonly Invoice[] | undefined): Invoice | null {
  const owed = (invoices ?? []).filter((i) => isOwed(i) && i.kind !== "addon").sort((a, b) => (a.due_date ?? "").localeCompare(b.due_date ?? ""));
  return owed[0] ?? null;
}

/** The body for starting a payment: only the fields the chosen method asks for, trimmed. */
export function payBody(invoiceId: string, option: Pick<PayOption, "provider" | "payer_fields">, values: Record<string, string>): Schemas["StartPaymentIn"] {
  const payer: Record<string, string> = {};
  for (const f of option.payer_fields) {
    const v = (values[f.name] ?? "").trim();
    if (v) payer[f.name] = v;
  }
  return { invoice_id: invoiceId, provider: option.provider, payer };
}

/** Whether every required field of a method is filled in. */
export function payerComplete(option: Pick<PayOption, "payer_fields">, values: Record<string, string>): boolean {
  return option.payer_fields.every((f) => !f.required || (values[f.name] ?? "").trim().length > 0);
}

/** Reads `?payment=...&attempt=...` (where a provider's page sends the owner back). */
export function returnParams(search: string): { attempt: string; payment: "success" | "cancelled" | null } | null {
  const p = new URLSearchParams(search);
  const attempt = p.get("attempt");
  if (!attempt) return null;
  const payment = p.get("payment");
  return { attempt, payment: payment === "success" || payment === "cancelled" ? payment : null };
}
