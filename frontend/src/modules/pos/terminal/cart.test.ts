import { describe, expect, it } from "vitest";

import {
  addItem, cartProblem, cartTotal, fingerprint, EMPTY_CART, isPriceOverride, newLeg, parseCart, parseHeld, patchLine, payProblem, paySummary,
  stepQuantity, toSaleLines, toSalePayments, type CartState, type CatalogItem,
} from "./cart";

const item = (over: Partial<CatalogItem> = {}): CatalogItem => ({
  product_id: "p1", sku: "NAIL", name: "Nails 2in", product_type: "stock", vat_rate: "16", is_batch_tracked: false, uom_id: "u", price: "120.50", stock: "10", ...over,
});

describe("cart lines", () => {
  it("adds a second unit to the same untouched line", () => {
    const lines = addItem(addItem([], item()), item());
    expect(lines).toHaveLength(1);
    expect(lines[0]!.quantity).toBe("2");
    expect(cartTotal(lines)).toBe(241);
  });

  it("starts a new line when the existing one was changed", () => {
    const first = addItem([], item());
    const changed = patchLine(first, first[0]!.key, { discount: "10" });
    expect(addItem(changed, item())).toHaveLength(2);
  });

  it("removes a line whose quantity reaches zero", () => {
    const lines = addItem([], item());
    expect(stepQuantity(lines, lines[0]!.key, -1)).toEqual([]);
  });

  it("applies the discount to the total", () => {
    const lines = addItem([], item({ price: "100" }));
    expect(cartTotal(patchLine(lines, lines[0]!.key, { discount: "15" }))).toBe(85);
  });

  it("needs a price when the product has none, and a reason for overrides and discounts", () => {
    const noPrice = addItem([], item({ price: null }));
    expect(cartProblem(noPrice)).toBe("price");
    const priced = patchLine(noPrice, noPrice[0]!.key, { price: "50" });
    expect(isPriceOverride(priced[0]!)).toBe(true);
    expect(cartProblem(priced)).toBe("reason");
    expect(cartProblem(patchLine(priced, priced[0]!.key, { reasonId: "r" }))).toBeNull();
  });

  it("sends the price only when it is not the list price", () => {
    const lines = addItem([], item());
    expect(toSaleLines(lines)[0]).not.toHaveProperty("unit_price");
    const changed = patchLine(lines, lines[0]!.key, { price: "100", reasonId: "r1" });
    expect(toSaleLines(changed)[0]).toMatchObject({ unit_price: "100", reason_code_id: "r1" });
  });
});

describe("payments", () => {
  it("gives change only on cash", () => {
    const s = paySummary(90, [newLeg("cash", 100)]);
    expect(s).toMatchObject({ paid: 100, remaining: 0, change: 10, overpaidByNonCash: false });
  });

  it("splits between card and cash", () => {
    const legs = [newLeg("card", 40), newLeg("cash", 60)];
    expect(paySummary(100, legs)).toMatchObject({ remaining: 0, change: 0 });
    expect(payProblem(100, legs, false)).toBeNull();
  });

  it("refuses non-cash above what is due, and short payments", () => {
    expect(payProblem(100, [newLeg("card", 120)], false)).toBe("overpaid");
    expect(payProblem(100, [newLeg("cash", 50)], false)).toBe("short");
    expect(payProblem(100, [], false)).toBe("empty");
  });

  it("wants a customer for credit and a code for mobile money", () => {
    expect(payProblem(100, [newLeg("credit", 100)], false)).toBe("customer");
    expect(payProblem(100, [newLeg("credit", 100)], true)).toBeNull();
    expect(payProblem(100, [newLeg("mobile_money", 100)], false)).toBe("code");
    expect(payProblem(100, [newLeg("mobile_money", 100, { ref: "ABC123" })], false)).toBeNull();
  });

  it("waits while a mobile money prompt is pending", () => {
    expect(payProblem(100, [newLeg("mobile_money", 100, { intentId: "i" })], false)).toBe("waiting");
    expect(payProblem(100, [newLeg("mobile_money", 100, { intentId: "i", confirmed: true, ref: "X1" })], false)).toBeNull();
  });

  it("sends the code and the account only where they apply", () => {
    const out = toSalePayments([newLeg("mobile_money", 50, { ref: " QX1 ", accountId: "a1" }), newLeg("cash", 50), newLeg("cash", 0)]);
    expect(out).toEqual([
      { method: "mobile_money", amount: "50", external_ref: "QX1", payment_account_id: "a1" },
      { method: "cash", amount: "50" },
    ]);
  });
});

describe("saved carts", () => {
  it("survives junk in storage", () => {
    expect(parseCart(null)).toEqual(EMPTY_CART);
    expect(parseCart("x")).toEqual(EMPTY_CART);
    expect(parseCart({ lines: [{ nonsense: true }, 5], legs: [{ method: "bitcoin" }] })).toEqual(EMPTY_CART);
    expect(parseHeld({ not: "a list" })).toEqual([]);
  });

  it("round-trips a cart", () => {
    const state: CartState = { ...EMPTY_CART, lines: addItem([], item()), customerId: "c1", legs: [newLeg("cash", 10)] };
    expect(parseCart(JSON.parse(JSON.stringify(state)))).toEqual(state);
  });

  it("changes the fingerprint when the sale changes", () => {
    const a: CartState = { ...EMPTY_CART, lines: addItem([], item()) };
    const b: CartState = { ...a, lines: addItem(a.lines, item()) };
    expect(fingerprint(a)).toBe(fingerprint({ ...a }));
    expect(fingerprint(a)).not.toBe(fingerprint(b));
  });
});
