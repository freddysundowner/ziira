/**
 * The cart and the payment legs as pure functions. Amounts are decimal strings; arithmetic here is only the on-screen
 * preview (the server recalculates and its figures are what the receipt shows). Rounding is half up to cents.
 */
import type { Schemas } from "@/sdk";

export type CatalogItem = Schemas["CatalogItemOut"];
export type PayMethod = "cash" | "card" | "mobile_money" | "credit" | "other";

export interface CartLine {
  key: string;
  productId: string;
  sku: string;
  name: string;
  /** Today's list price (tax-inclusive), or "" when the product has none. */
  listPrice: string;
  /** The price charged; equals listPrice unless overridden. */
  price: string;
  quantity: string;
  /** Discount on the whole line, as an amount. */
  discount: string;
  reasonId: string;
  stock: string;
}

export interface PayLeg {
  key: string;
  method: PayMethod;
  amount: string;
  /** Mobile money code or card slip number. */
  ref: string;
  accountId: string;
  phone: string;
  /** Mobile money prompt sent to the customer's phone. */
  intentId: string;
  /** Idempotency key of that prompt, so a retry never prompts twice. */
  intentKey: string;
  /** The prompt succeeded: the money is in, the amount can no longer change. */
  confirmed: boolean;
}

export interface CartState {
  lines: CartLine[];
  customerId: string;
  customerName: string;
  customerPhone: string;
  legs: PayLeg[];
  /** The id the server uses to record this exact sale once; renewed whenever the content changes. */
  attempt: { id: string; fingerprint: string } | null;
}

export interface HeldSale {
  id: string;
  label: string;
  savedAt: string;
  lines: CartLine[];
  customerId: string;
  customerName: string;
  customerPhone: string;
}

export const EMPTY_CART: CartState = { lines: [], customerId: "", customerName: "", customerPhone: "", legs: [], attempt: null };

export const num = (s: string | number | null | undefined): number => {
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
};
const cents = (n: number): number => Math.round((n + Number.EPSILON) * 100);
export const round2 = (n: number): number => cents(n) / 100;
/** A number as the API wants it: plain decimal text, never exponent notation. */
export const text = (n: number): string => String(round2(n));

export function lineGross(l: CartLine): number {
  return round2(num(l.quantity) * num(l.price));
}
export function lineTotal(l: CartLine): number {
  return Math.max(0, round2(lineGross(l) - num(l.discount)));
}
export const cartTotal = (lines: CartLine[]): number => round2(lines.reduce((s, l) => s + lineTotal(l), 0));
export const cartDiscount = (lines: CartLine[]): number => round2(lines.reduce((s, l) => s + num(l.discount), 0));
export const itemCount = (lines: CartLine[]): number => lines.reduce((s, l) => s + num(l.quantity), 0);

/** The price differs from the list price (or there is none): needs the override permission and a reason. */
export function isPriceOverride(l: CartLine): boolean {
  return l.listPrice === "" || cents(num(l.price)) !== cents(num(l.listPrice));
}
export const needsReason = (l: CartLine): boolean => isPriceOverride(l) || num(l.discount) > 0;

export type LineProblem = "price" | "quantity" | "reason" | "discount";
export function lineProblem(l: CartLine): LineProblem | null {
  if (num(l.quantity) <= 0) return "quantity";
  if (l.price.trim() === "") return "price";
  if (num(l.discount) > lineGross(l)) return "discount";
  if (needsReason(l) && !l.reasonId) return "reason";
  return null;
}
export const cartProblem = (lines: CartLine[]): LineProblem | null => lines.map(lineProblem).find((p) => p !== null) ?? null;

export function lineFromItem(item: CatalogItem): CartLine {
  const price = item.price === null || item.price === undefined ? "" : String(item.price);
  return {
    key: crypto.randomUUID(), productId: item.product_id, sku: item.sku, name: item.name, listPrice: price, price, quantity: "1",
    discount: "0", reasonId: "", stock: item.stock === null || item.stock === undefined ? "" : String(item.stock),
  };
}

/** Add one of a product: another unit on its untouched line, else a new line. */
export function addItem(lines: CartLine[], item: CatalogItem): CartLine[] {
  const same = lines.find((l) => l.productId === item.product_id && !isPriceOverride(l) && num(l.discount) === 0);
  if (!same) return [...lines, lineFromItem(item)];
  return lines.map((l) => (l === same ? { ...l, quantity: String(round3(num(l.quantity) + 1)) } : l));
}
const round3 = (n: number): number => Math.round((n + Number.EPSILON) * 1000) / 1000;

/** Change a line's quantity by `delta`; a line that reaches zero is removed. */
export function stepQuantity(lines: CartLine[], key: string, delta: number): CartLine[] {
  return lines.flatMap((l) => {
    if (l.key !== key) return [l];
    const q = round3(num(l.quantity) + delta);
    return q > 0 ? [{ ...l, quantity: String(q) }] : [];
  });
}
export const patchLine = (lines: CartLine[], key: string, patch: Partial<CartLine>): CartLine[] => lines.map((l) => (l.key === key ? { ...l, ...patch } : l));
export const removeLine = (lines: CartLine[], key: string): CartLine[] => lines.filter((l) => l.key !== key);

/** Lines in the API's shape. The price is sent only when it is not the list price. */
export function toSaleLines(lines: CartLine[]): Schemas["SaleLineIn"][] {
  return lines.map((l) => ({
    product_id: l.productId,
    quantity: l.quantity,
    ...(isPriceOverride(l) ? { unit_price: l.price } : {}),
    discount: l.discount || "0",
    ...(needsReason(l) && l.reasonId ? { reason_code_id: l.reasonId } : {}),
  }));
}

// ----------------------------------------------------------------------------- payments
export function newLeg(method: PayMethod, amount: number, defaults: Partial<PayLeg> = {}): PayLeg {
  return {
    key: crypto.randomUUID(), method, amount: amount > 0 ? text(amount) : "", ref: "", accountId: "", phone: "", intentId: "", intentKey: "", confirmed: false,
    ...defaults,
  };
}

export interface PaySummary {
  paid: number;
  remaining: number;
  change: number;
  /** Non-cash legs add up to more than is due: only cash may be more than is due. */
  overpaidByNonCash: boolean;
}

export function paySummary(total: number, legs: PayLeg[]): PaySummary {
  const cash = legs.filter((l) => l.method === "cash").reduce((s, l) => s + num(l.amount), 0);
  const other = legs.filter((l) => l.method !== "cash").reduce((s, l) => s + num(l.amount), 0);
  const paid = round2(cash + other);
  const remaining = Math.max(0, round2(total - paid));
  const due = Math.max(0, round2(total - other));
  return { paid, remaining, change: paid >= total ? Math.max(0, round2(cash - due)) : 0, overpaidByNonCash: cents(other) > cents(total) };
}

/** Why the sale cannot be completed yet, or null. */
export type PayProblem = "empty" | "short" | "overpaid" | "code" | "customer" | "waiting";
export function payProblem(total: number, legs: PayLeg[], hasCustomer: boolean): PayProblem | null {
  const live = legs.filter((l) => num(l.amount) > 0);
  if (live.length === 0 || total <= 0) return "empty";
  if (live.some((l) => l.method === "credit") && !hasCustomer) return "customer";
  if (live.some((l) => l.method === "mobile_money" && l.intentId && !l.confirmed)) return "waiting";
  if (live.some((l) => l.method === "mobile_money" && !l.ref.trim())) return "code";
  const s = paySummary(total, live);
  if (s.overpaidByNonCash) return "overpaid";
  return s.remaining > 0 ? "short" : null;
}

export const saleLegs = (legs: PayLeg[]): PayLeg[] => legs.filter((l) => num(l.amount) > 0);

export function toSalePayments(legs: PayLeg[]): Schemas["SalePaymentIn"][] {
  return saleLegs(legs).map((l) => ({
    method: l.method,
    amount: l.amount,
    ...(l.ref.trim() ? { external_ref: l.ref.trim() } : {}),
    ...(l.method === "mobile_money" && l.accountId ? { payment_account_id: l.accountId } : {}),
  }));
}

/** Identifies the exact content of a sale: the same fingerprint may reuse the same server-side id. */
export function fingerprint(state: CartState): string {
  return JSON.stringify([state.customerId, toSaleLines(state.lines), toSalePayments(state.legs)]);
}

/** Legs that took no money yet are dropped when the cart changes; collected mobile money stays. */
export const keepCollected = (legs: PayLeg[]): PayLeg[] => legs.filter((l) => l.confirmed || (l.method === "mobile_money" && l.intentId));

// ----------------------------------------------------------------------------- storage shape
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const str = (v: unknown): string => (typeof v === "string" ? v : "");

function parseLine(v: unknown): CartLine | null {
  if (!isObject(v) || !str(v.productId)) return null;
  return {
    key: str(v.key) || crypto.randomUUID(), productId: str(v.productId), sku: str(v.sku), name: str(v.name), listPrice: str(v.listPrice),
    price: str(v.price), quantity: str(v.quantity) || "1", discount: str(v.discount) || "0", reasonId: str(v.reasonId), stock: str(v.stock),
  };
}
function parseLeg(v: unknown): PayLeg | null {
  if (!isObject(v)) return null;
  const method = str(v.method) as PayMethod;
  if (!["cash", "card", "mobile_money", "credit", "other"].includes(method)) return null;
  return {
    key: str(v.key) || crypto.randomUUID(), method, amount: str(v.amount), ref: str(v.ref), accountId: str(v.accountId), phone: str(v.phone),
    intentId: str(v.intentId), intentKey: str(v.intentKey), confirmed: v.confirmed === true,
  };
}
const list = <T>(v: unknown, parse: (x: unknown) => T | null): T[] => (Array.isArray(v) ? v.map(parse).filter((x): x is T => x !== null) : []);

/** Read a saved cart defensively: whatever is in storage, the terminal starts. */
export function parseCart(raw: unknown): CartState {
  if (!isObject(raw)) return EMPTY_CART;
  const a = raw.attempt;
  return {
    lines: list(raw.lines, parseLine), customerId: str(raw.customerId), customerName: str(raw.customerName), customerPhone: str(raw.customerPhone),
    legs: list(raw.legs, parseLeg),
    attempt: isObject(a) && str(a.id) ? { id: str(a.id), fingerprint: str(a.fingerprint) } : null,
  };
}
export function parseHeld(raw: unknown): HeldSale[] {
  return list(raw, (v) => {
    if (!isObject(v) || !str(v.id)) return null;
    return {
      id: str(v.id), label: str(v.label), savedAt: str(v.savedAt), lines: list(v.lines, parseLine), customerId: str(v.customerId),
      customerName: str(v.customerName), customerPhone: str(v.customerPhone),
    };
  });
}
