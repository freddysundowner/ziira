import { describe, expect, it } from "vitest";

import { chosenReturnLines, overReturned, sumAmounts, variancePreview } from "./lib";

describe("sumAmounts", () => {
  it("adds decimal strings without float noise", () => {
    expect(sumAmounts(["0.1", "0.2", "100.50"])).toBe(100.8);
  });
  it("ignores empty and invalid values", () => {
    expect(sumAmounts(["5", "", null, undefined, "x"])).toBe(5);
  });
});

describe("variancePreview", () => {
  it("is null until a number is typed", () => {
    expect(variancePreview("100", "")).toBeNull();
    expect(variancePreview("100", "abc")).toBeNull();
  });
  it("is counted minus expected", () => {
    expect(variancePreview("1500.00", "1450.50")).toBe(-49.5);
    expect(variancePreview("100", "100")).toBe(0);
  });
});

describe("returns", () => {
  it("keeps only lines with a quantity", () => {
    expect(chosenReturnLines({ a: "0", b: "2", c: "", d: "1.5" })).toEqual([
      { sale_line_id: "b", quantity: "2" },
      { sale_line_id: "d", quantity: "1.5" },
    ]);
  });
  it("finds lines returned beyond what was sold", () => {
    expect(overReturned({ a: "3", b: "1" }, { a: "2", b: "1" })).toEqual(["a"]);
  });
});
