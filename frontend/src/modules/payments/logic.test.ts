import { describe, expect, it } from "vitest";

import { flattenTotals, hasPending, isFinalIntent, summarise, sumDecimals } from "./logic";

describe("sumDecimals", () => {
  it("adds exactly", () => {
    expect(sumDecimals(["0.10", "0.20", "1"])).toBe("1.30");
    expect(sumDecimals([])).toBe("0");
    expect(sumDecimals(["-0.05", "0.01"])).toBe("-0.04");
  });
});

describe("intents", () => {
  it("knows which states are final", () => {
    expect(isFinalIntent("pending")).toBe(false);
    for (const s of ["succeeded", "failed", "cancelled", "timeout"]) expect(isFinalIntent(s)).toBe(true);
  });
  it("detects pending rows", () => {
    expect(hasPending([{ status: "succeeded" }, { status: "pending" }])).toBe(true);
    expect(hasPending([{ status: "failed" }])).toBe(false);
    expect(hasPending(undefined)).toBe(false);
  });
});

describe("summarise", () => {
  it("totals money in and out, per method, ignoring reversed payments", () => {
    const s = summarise([
      { direction: "in", method: "cash", amount: "100.00", status: "posted" },
      { direction: "in", method: "mobile_money", amount: "50.50", status: "posted" },
      { direction: "in", method: "cash", amount: "20.00", status: "posted" },
      { direction: "in", method: "cash", amount: "999.00", status: "reversed" },
      { direction: "out", method: "cash", amount: "10.00", status: "posted" },
    ]);
    expect(s.received).toBe("170.50");
    expect(s.paidOut).toBe("10.00");
    expect(s.count).toBe(4);
    expect(s.byMethod).toEqual([{ method: "cash", amount: "120.00" }, { method: "mobile_money", amount: "50.50" }]);
  });
});

describe("flattenTotals", () => {
  it("flattens nested figures", () => {
    expect(flattenTotals({ cash: { expected: "10", banked: null }, variance: "0" })).toEqual([
      { path: ["cash", "expected"], value: "10" }, { path: ["cash", "banked"], value: "" }, { path: ["variance"], value: "0" },
    ]);
  });
});
