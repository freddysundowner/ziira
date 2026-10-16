import { describe, expect, it } from "vitest";

import { emptyPriceForm, priceProblems, priceState, toPriceIn } from "./price";

const now = new Date("2026-06-01T00:00:00Z");

describe("priceState", () => {
  const current = new Set(["p2"]);
  it("tells in force, scheduled, withdrawn and replaced rows apart", () => {
    expect(priceState({ id: "p2", effective_from: "2026-05-01T00:00:00Z" }, current, now)).toBe("current");
    expect(priceState({ id: "p1", effective_from: "2026-01-01T00:00:00Z" }, current, now)).toBe("superseded");
    expect(priceState({ id: "p3", effective_from: "2026-07-01T00:00:00Z" }, current, now)).toBe("scheduled");
    expect(priceState({ id: "p4", effective_from: "2026-05-01T00:00:00Z", withdrawn: true }, current, now)).toBe("withdrawn");
  });
});

describe("price form", () => {
  it("needs a three letter currency and an amount with at most two decimals", () => {
    expect(priceProblems(emptyPriceForm())).toEqual({ currency: "currency", amount: "amount" });
    expect(priceProblems({ ...emptyPriceForm(), currency: "usd", amount: "19.99" })).toEqual({});
    expect(priceProblems({ ...emptyPriceForm(), currency: "usd", amount: "19.999" }).amount).toBe("amount");
  });
  it("does not need an amount to stop offering a price", () => {
    expect(priceProblems({ ...emptyPriceForm(), currency: "usd", withdrawn: true })).toEqual({});
    expect(toPriceIn({ ...emptyPriceForm(), currency: "usd", withdrawn: true }).amount).toBe("0");
  });
  it("sends a capital currency and a start of day for the date, or none to start now", () => {
    const now = toPriceIn({ ...emptyPriceForm(), currency: "kes", amount: "100" });
    expect(now.currency).toBe("KES");
    expect(now.effective_from).toBeNull();
    expect(toPriceIn({ ...emptyPriceForm(), currency: "kes", amount: "100", effective_from: "2026-09-01" }).effective_from).toMatch(/^2026-0[89]-/);
  });
});
