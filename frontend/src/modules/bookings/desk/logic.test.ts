import { describe, expect, it } from "vitest";

import type { Checkout, Offer } from "../types";
import { cleanAmount, draftBody, draftFromCheckout, fillFromServer, hasDiscount, isPositive, nextStep, productLine, quickOffers, serviceLine, settlement, staffOnLines, toUnits } from "./logic";

const offer = (id: string, over: Partial<Offer> = {}) => ({ id, name: id, is_active: true, kind: "service", ...over }) as Offer;

describe("quickOffers", () => {
  it("keeps active non-class offers, at most six", () => {
    const list = [offer("a"), offer("b", { is_active: false }), offer("c", { kind: "class" }), ...["d", "e", "f", "g", "h", "i"].map((x) => offer(x))];
    expect(quickOffers(list).map((o) => o.id)).toEqual(["a", "d", "e", "f", "g", "h"]);
  });
});

describe("nextStep", () => {
  it("follows the visit", () => {
    expect(nextStep("confirmed")).toBe("check-in");
    expect(nextStep("checked_in")).toBe("start");
    expect(nextStep("in_service")).toBe("finish");
    expect(nextStep("completed")).toBeNull();
  });
});

describe("amount text", () => {
  it("parses exactly", () => {
    expect(toUnits("12.5")).toBe(125000n);
    expect(toUnits("0.1")).toBe(1000n);
    expect(toUnits("abc")).toBeNull();
    expect(toUnits("")).toBeNull();
  });
  it("knows positive and cleans", () => {
    expect(isPositive("0.01")).toBe(true);
    expect(isPositive("0")).toBe(false);
    expect(cleanAmount("5.")).toBe("5");
    expect(cleanAmount("")).toBe("0");
    expect(cleanAmount(".")).toBe("0");
  });
  it("compares payments to the total without float error", () => {
    expect(settlement("0.30", ["0.10", "0.20"])).toBe("exact");
    expect(settlement("100.00", ["40", "50"])).toBe("short");
    expect(settlement("100.00", ["60", "50"])).toBe("over");
    expect(settlement("0", [])).toBe("exact");
  });
});

describe("draft", () => {
  const co = {
    discount_kind: "percent", discount_value: "10", discount_reason_id: null, discount_note: null, note: null, payer_customer_id: null, copay_amount: null, preauth_ref: null,
    lines: [{ id: "l1", kind: "service", appointment_id: "ap", offer_id: "o1", product_id: null, fee_id: null, description: "Cut", quantity: "1", unit_price: "20.00", discount: "0", resource_id: "r1", variant: null, credit_quantity: "1" }],
  } as unknown as Checkout;
  it("round trips through the body", () => {
    const d = draftFromCheckout(co);
    expect(d.lines[0]?.use_credit).toBe(true);
    const body = draftBody(d);
    expect(body.lines[0]).toMatchObject({ kind: "service", unit_price: "20.00", appointment_id: "ap", resource_id: "r1", use_credit: true, product_id: null });
    expect(body.discount_kind).toBe("percent");
    expect(body.copay_amount).toBeNull();
  });
  it("sends no price for a new service and no payer terms without a payer", () => {
    const d = draftFromCheckout(co);
    d.lines.push(serviceLine({ id: "o2", name: "Wash" }));
    d.copay_amount = "5";
    d.preauth_ref = "x";
    const body = draftBody(d);
    expect(body.lines[1]?.unit_price).toBeNull();
    expect(body.copay_amount).toBeNull();
    expect(body.preauth_ref).toBeNull();
  });
  it("needs a reason for any discount and lists staff once", () => {
    const d = draftFromCheckout(co);
    d.discount_value = "0";
    expect(hasDiscount(d)).toBe(false);
    d.lines.push(productLine({ id: "p", name: "Gel", price: "4.00" }));
    expect(staffOnLines(d.lines)).toEqual(["r1"]);
    d.lines[1]!.discount = "1";
    expect(hasDiscount(d)).toBe(true);
  });
  it("fills in missing prices from the server by position", () => {
    const d = draftFromCheckout(co);
    d.lines.push(serviceLine({ id: "o2", name: "Wash" }));
    const server = { lines: [co.lines[0], { ...co.lines[0], unit_price: "15.00", description: "Wash" }] } as unknown as Checkout;
    expect(fillFromServer(d.lines, server)[1]?.unit_price).toBe("15.00");
  });
});
