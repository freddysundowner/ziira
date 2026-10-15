import { describe, expect, it } from "vitest";

import { AGING_AFTER_MS, freshnessOf, needsRefresh, REFRESH_AFTER_MS, showAsOf, STALE_AFTER_MS } from "./freshness";

describe("how old the saved prices are", () => {
  it("grows from fresh to aging to stale", () => {
    expect(freshnessOf(1000, 1000 + AGING_AFTER_MS)).toBe("fresh");
    expect(freshnessOf(1000, 1001 + AGING_AFTER_MS)).toBe("aging");
    expect(freshnessOf(1000, 1001 + STALE_AFTER_MS)).toBe("stale");
  });
  it("is none when nothing is saved", () => {
    expect(freshnessOf(null, 5)).toBe("none");
    expect(freshnessOf(0, 5)).toBe("none");
    expect(freshnessOf(undefined, 5)).toBe("none");
  });
});

describe("when to fetch a new copy", () => {
  it("when there is none, or it is a few minutes old, and only with a connection", () => {
    expect(needsRefresh(null, 10, true)).toBe(true);
    expect(needsRefresh(1000, 1000 + REFRESH_AFTER_MS - 1, true)).toBe(false);
    expect(needsRefresh(1000, 1000 + REFRESH_AFTER_MS, true)).toBe(true);
    expect(needsRefresh(null, 10, false)).toBe(false);
    expect(needsRefresh(1000, 1e12, false)).toBe(false);
  });
});

describe("when to say 'prices as of'", () => {
  it("always offline, and online only when the copy is not fresh", () => {
    expect(showAsOf("fresh", false)).toBe(true);
    expect(showAsOf("fresh", true)).toBe(false);
    expect(showAsOf("aging", true)).toBe(true);
    expect(showAsOf("stale", true)).toBe(true);
    expect(showAsOf("none", false)).toBe(false);
  });
});
