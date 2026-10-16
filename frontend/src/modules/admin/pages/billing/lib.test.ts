import { describe, expect, it } from "vitest";

import { bannerTone, changeRequestBody, intervalsFor, invoiceTone, isOwed, licenceTone, owedEntries, pickPrice, priceCurrency, statusTone, usageLevel, type PublicPlan } from "./lib";

const plan = (prices: [string, string, string][]): Pick<PublicPlan, "prices"> => ({
  prices: prices.map(([currency, interval, amount]) => ({ currency, interval, amount, tax_inclusive: false })),
});

describe("usageLevel", () => {
  it("is ok below 80%, near from 80%, over above the limit", () => {
    expect(usageLevel(7, 10)).toEqual({ pct: 70, level: "ok" });
    expect(usageLevel(8, 10)).toEqual({ pct: 80, level: "near" });
    expect(usageLevel(10, 10)).toEqual({ pct: 100, level: "near" });
    expect(usageLevel(11, 10)).toEqual({ pct: 110, level: "over" });
  });
  it("has no percentage when unlimited", () => {
    expect(usageLevel(500, null)).toEqual({ pct: null, level: "ok" });
  });
  it("treats a limit of zero as over once anything is used", () => {
    expect(usageLevel(1, 0).level).toBe("over");
    expect(usageLevel(0, 0).level).toBe("ok");
  });
});

describe("prices", () => {
  const p = plan([["USD", "month", "10"], ["USD", "year", "100"], ["EUR", "month", "9"]]);
  it("prefers the business currency, otherwise the plan's first", () => {
    expect(priceCurrency(p, "eur")).toBe("EUR");
    expect(priceCurrency(p, "KES")).toBe("USD");
    expect(priceCurrency(plan([]), "USD")).toBeNull();
  });
  it("lists the intervals offered in a currency, month first", () => {
    expect(intervalsFor(p, "USD")).toEqual(["month", "year"]);
    expect(intervalsFor(p, "EUR")).toEqual(["month"]);
  });
  it("picks the price for an interval, or the currency's first when it is not offered", () => {
    expect(pickPrice(p, "USD", "year")?.amount).toBe("100");
    expect(pickPrice(p, "EUR", "year")?.amount).toBe("9");
    expect(pickPrice(p, "KES", "month")).toBeNull();
  });
});

describe("tones", () => {
  it("maps subscription statuses", () => {
    expect(statusTone("active")).toBe("ok");
    expect(statusTone("trialing")).toBe("info");
    expect(statusTone("grace")).toBe("warn");
    expect(statusTone("suspended")).toBe("bad");
    expect(statusTone("unmanaged")).toBe("neutral");
  });
  it("maps licence and invoice states", () => {
    expect(licenceTone("valid")).toBe("ok");
    expect(licenceTone("clock_rollback")).toBe("bad");
    expect(invoiceTone("paid")).toBe("ok");
    expect(invoiceTone("issued")).toBe("warn");
  });
  it("maps banner levels", () => {
    expect([bannerTone("info"), bannerTone("warning"), bannerTone("blocked"), bannerTone("other")]).toEqual(["info", "warn", "bad", "info"]);
  });
});

describe("owed", () => {
  it("flags unpaid invoices with a balance", () => {
    expect(isOwed({ status: "issued", balance: "5.00" })).toBe(true);
    expect(isOwed({ status: "issued", balance: "0.00" })).toBe(false);
    expect(isOwed({ status: "paid", balance: "0.00" })).toBe(false);
  });
  it("drops zero amounts", () => {
    expect(owedEntries({ USD: "12.50", EUR: "0.00" })).toEqual([["USD", "12.50"]]);
  });
});

describe("changeRequestBody", () => {
  it("sends the plan, interval and currency, and leaves blank coupons out", () => {
    expect(changeRequestBody("pro", { currency: "usd", interval: "year" }, "  ", " hello ")).toEqual({ plan_code: "pro", interval: "year", currency: "USD", note: "hello" });
    expect(changeRequestBody("pro", null, " SAVE10 ", "")).toEqual({ plan_code: "pro", coupon_code: "SAVE10", note: "" });
  });
});
