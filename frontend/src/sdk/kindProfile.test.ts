import { describe, expect, it } from "vitest";

import { profileFor, SIDEBAR, TILL_PAGES } from "./kindProfile";

describe("kindProfile", () => {
  it("reads a tutor, school or training centre from the education pack, whatever the edition", () => {
    expect(profileFor("services", new Set(["bookings", "pack_education"]))).toBe("education");
    expect(profileFor("full", new Set(["pack_education"]))).toBe("education");
    expect(profileFor("services", new Set(["bookings"]))).toBe("services");
  });
  it("reads a pharmacy from its pack, keeps the till and puts Sell and Stock first", () => {
    expect(profileFor("retail", new Set(["pos", "pack_pharmacy"]))).toBe("pharmacy");
    expect(profileFor("distribution", new Set(["pack_pharmacy"]))).toBe("pharmacy");
    expect(profileFor("retail", new Set(["pos"]))).toBe("retail");
    expect(SIDEBAR.pharmacy.till).toBe(true);
    expect(SIDEBAR.pharmacy.order.slice(0, 2)).toEqual(["sell", "stock"]);
    expect(SIDEBAR.pharmacy.open).toEqual(["sell", "stock"]);
  });
  it("lists Services first and hides the till for a school", () => {
    expect(SIDEBAR.education.order[0]).toBe("services");
    expect(SIDEBAR.education.open).toContain("services");
    expect(SIDEBAR.education.till).toBe(false);
    expect(TILL_PAGES.length).toBeGreaterThan(0);
  });
});
