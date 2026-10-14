import { describe, expect, it } from "vitest";

import { dueToIso, isOverdueActivity, overdueOf, sumDecimals } from "./logic";

describe("sumDecimals", () => {
  it("adds without float error", () => {
    expect(sumDecimals(["0.10", "0.20"])).toBe("0.30");
    expect(sumDecimals(["1000000.05", "2.95"])).toBe("1000003.00");
  });
  it("handles empty, whole and negative values", () => {
    expect(sumDecimals([])).toBe("0");
    expect(sumDecimals(["5", "7"])).toBe("12");
    expect(sumDecimals(["-1.50", "0.25"])).toBe("-1.25");
    expect(sumDecimals(["0.05", "-0.10"])).toBe("-0.05");
  });
});

describe("overdueOf", () => {
  it("leaves out what is not yet due", () => {
    expect(overdueOf({ not_due: "100.00", "1_30": "10.00", "31_60": "5.50", over_90: "1.00" })).toBe("16.50");
  });
});

describe("isOverdueActivity", () => {
  const now = new Date("2026-05-10T10:00:00Z");
  it("is overdue only when open and past due", () => {
    expect(isOverdueActivity({ due_at: "2026-05-09T10:00:00Z", done_at: null }, now)).toBe(true);
    expect(isOverdueActivity({ due_at: "2026-05-11T10:00:00Z", done_at: null }, now)).toBe(false);
    expect(isOverdueActivity({ due_at: "2026-05-09T10:00:00Z", done_at: "2026-05-09T12:00:00Z" }, now)).toBe(false);
    expect(isOverdueActivity({ due_at: null, done_at: null }, now)).toBe(false);
  });
});

describe("dueToIso", () => {
  it("returns null for empty or invalid input", () => {
    expect(dueToIso("")).toBeNull();
    expect(dueToIso("nonsense")).toBeNull();
    expect(dueToIso("2026-05-10T09:30")).toMatch(/^2026-05-10T|^2026-05-09T/);
  });
});
