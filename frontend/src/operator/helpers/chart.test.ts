import { describe, expect, it } from "vitest";

import { areaPath, type Box, describeSeries, donutSlices, linePath, nearestIndex, niceMax, ticks, trend, xAt, yAt } from "./chart";

const box: Box = { width: 110, height: 70, left: 10, right: 10, top: 10, bottom: 10 };      // a 90 x 50 plot area

describe("axis helpers", () => {
  it("rounds a maximum up to 1, 2, 5 or 10 times a power of ten", () => {
    expect([0, -4, 1, 1.5, 2, 3, 5, 7, 10, 12, 480, 5001].map(niceMax)).toEqual([1, 1, 1, 2, 2, 5, 5, 10, 10, 20, 500, 10000]);
  });
  it("gives evenly spaced ticks from zero to the nice maximum", () => {
    expect(ticks(480, 4)).toEqual([0, 125, 250, 375, 500]);
  });
});

describe("positions", () => {
  it("spreads points over the plot area, first at the left edge and last at the right", () => {
    expect([0, 1, 2].map((i) => xAt(i, 3, box))).toEqual([10, 55, 100]);
    expect(xAt(0, 1, box)).toBe(55);                                                        // one point sits in the middle
  });
  it("puts zero on the baseline and the maximum at the top, clamping what is outside", () => {
    expect([0, 50, 100, 150, -5].map((v) => yAt(v, 100, box))).toEqual([60, 35, 10, 10, 60]);
  });
  it("finds the nearest point to a pointer", () => {
    expect([0, 10, 32, 33, 55, 100, 400].map((x) => nearestIndex(x, 3, box))).toEqual([0, 0, 0, 1, 1, 2, 2]);
    expect(nearestIndex(50, 1, box)).toBe(0);
  });
});

describe("paths", () => {
  it("draws a line through the points", () => {
    expect(linePath([0, 100, 50], 100, box)).toBe("M10 60 L55 10 L100 35");
  });
  it("closes an area down to the baseline, and draws nothing for no data", () => {
    expect(areaPath([0, 100, 50], 100, box)).toBe("M10 60 L55 10 L100 35 L100 60 L10 60 Z");
    expect(areaPath([], 100, box)).toBe("");
  });
  it("cuts a donut into slices that add up to the whole", () => {
    const slices = donutSlices([1, 1, 2], 60, 38);
    expect(slices.map((s) => s.share)).toEqual([0.25, 0.25, 0.5]);
    expect(slices.every((s) => s.path.startsWith("M") && s.path.endsWith("Z"))).toBe(true);
    expect(donutSlices([0, 0], 60, 38)).toEqual([]);
    expect(donutSlices([5], 60, 38)).toHaveLength(1);                                       // one full ring still has a path
  });
});

describe("words for the chart", () => {
  it("describes a series for a screen reader", () => {
    expect(describeSeries(["Jan", "Feb"], [5, 7], (n) => `${n} units`)).toBe("Jan: 5 units, Feb: 7 units");
  });
  it("tells the change from the first to the last value", () => {
    expect(trend([100, 150])).toBe(0.5);
    expect(trend([0, 5])).toBeNull();
    expect(trend([])).toBeNull();
  });
});
