import { describe, expect, it } from "vitest";

import { credits, daysBetween, emptyLine, linePreview, linesTotal, memberTone, monthsIn, runTone, sumDecimals } from "./logic";

describe("credits", () => {
  it("shows whole credits plainly and part credits with what they need", () => {
    expect(credits("4.00")).toBe("4");
    expect(credits("1.50")).toBe("1.5");
    expect(credits("-2.00")).toBe("-2");
    expect(credits(null)).toBe("0");
  });
});

describe("sumDecimals", () => {
  it("adds without float error", () => {
    expect(sumDecimals(["0.10", "0.20"])).toBe("0.30");
    expect(sumDecimals(["-1.50", "0.25"])).toBe("-1.25");
    expect(sumDecimals([])).toBe("0");
  });
});

describe("linePreview and linesTotal", () => {
  it("is quantity times price less discount, in cents", () => {
    expect(linePreview("3", "100.00")).toBe("300.00");
    expect(linePreview("1", "58.00", "8.00")).toBe("50.00");
    expect(linePreview("2.5", "20.00")).toBe("50.00");
    expect(linePreview("x", "1")).toBe("0.00");
  });
  it("totals only the lines that are filled in", () => {
    const a = { ...emptyLine(), product_id: "p1", quantity: "3", unit_price: "100.00" };
    const b = { ...emptyLine(), product_id: "p2", quantity: "1", unit_price: "58.00", discount: "8.00" };
    const unfinished = { ...emptyLine(), quantity: "5", unit_price: "9.00" };
    expect(linesTotal([a, b, unfinished])).toBe("350.00");
    expect(linesTotal([])).toBe("0");
  });
});

describe("dates and intervals", () => {
  it("counts whole days across months and leap years", () => {
    expect(daysBetween("2026-01-15", "2026-02-01")).toBe(17);
    expect(daysBetween("2028-02-28", "2028-03-01")).toBe(2);
    expect(daysBetween("2026-03-01", "2026-02-01")).toBe(-28);
  });
  it("knows the months an interval covers", () => {
    expect([monthsIn("month"), monthsIn("quarter"), monthsIn("year"), monthsIn("week")]).toEqual([1, 3, 12, 0]);
  });
});

describe("tones", () => {
  it("separate healthy from needs-attention", () => {
    expect(memberTone("active")).toBe("ok");
    expect(memberTone("paused")).toBe("warn");
    expect(runTone("failed")).toBe("bad");
    expect(runTone("pending_review")).toBe("info");
    expect(memberTone("mystery")).toBe("neutral");
  });
});
