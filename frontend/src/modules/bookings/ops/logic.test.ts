import { describe, expect, it } from "vitest";

import { clampWeeks, groupByDay, monthRange, overdueTone, periodRange, weekBounds, weekDays, wholeDays, wholeOrNull } from "./logic";

describe("weeks", () => {
  it("runs Monday to Sunday and bounds the week on the company's clock", () => {
    const w = weekBounds("2026-10-21", "Africa/Nairobi");
    expect(w.first).toBe("2026-10-19");
    expect(w.last).toBe("2026-10-25");
    expect(w.startIso).toBe("2026-10-19T00:00:00+03:00");
    expect(w.endIso).toBe("2026-10-26T00:00:00+03:00");
    expect(weekDays(w.first)).toHaveLength(7);
  });
  it("groups by the company's day, in order", () => {
    const rows = [{ starts_at: "2026-10-20T20:30:00Z" }, { starts_at: "2026-10-19T06:00:00Z" }, { starts_at: "2026-10-19T05:00:00Z" }];
    const g = groupByDay(rows, "Africa/Nairobi");
    expect(g.map((x) => x.day)).toEqual(["2026-10-19", "2026-10-20"]);   // 20:30Z is 23:30 on the 20th in Nairobi
  });
});

describe("periods", () => {
  it("knows month ends", () => {
    expect(monthRange("2026-02-10")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(monthRange("2026-01-15", -1)).toEqual({ start: "2025-12-01", end: "2025-12-31" });
  });
  it("uses presets and repairs a backwards custom range", () => {
    expect(periodRange("lastMonth", "2026-03-05", { start: "", end: "" })).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(periodRange("custom", "2026-03-05", { start: "2026-03-10", end: "2026-03-01" })).toEqual({ start: "2026-03-10", end: "2026-03-10" });
  });
});

describe("small helpers", () => {
  it("tones overdue days", () => {
    expect(overdueTone(3)).toBe("info");
    expect(overdueTone(20)).toBe("warn");
    expect(overdueTone(90)).toBe("bad");
  });
  it("keeps weeks within 1 to 52", () => {
    expect(clampWeeks("0")).toBe(1);
    expect(clampWeeks("99")).toBe(52);
    expect(clampWeeks("abc")).toBe(1);
    expect(clampWeeks("8")).toBe(8);
  });
  it("reads an optional whole number", () => {
    expect(wholeOrNull("")).toBeNull();
    expect(wholeOrNull("0")).toBeNull();
    expect(wholeOrNull("12")).toBe(12);
  });
  it("covers whole days for time off", () => {
    expect(wholeDays("2026-10-19", "2026-10-20", "Africa/Nairobi")).toEqual({ startsAt: "2026-10-19T00:00:00+03:00", endsAt: "2026-10-21T00:00:00+03:00" });
  });
});
