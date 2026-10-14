import { describe, expect, it } from "vitest";

import { COUNTRIES, countryByCode, CURRENCIES } from "./countries";

describe("registration countries", () => {
  it("has well-formed, unique entries", () => {
    const codes = COUNTRIES.map((c) => c.code);
    expect(new Set(codes).size).toBe(codes.length);
    for (const c of COUNTRIES) {
      expect(c.code).toMatch(/^[A-Z]{2}$/);
      expect(c.calling).toMatch(/^[1-9][0-9]{0,2}$/);   // 1 to 3 digits, what the backend accepts
      expect(c.currency).toMatch(/^[A-Z]{3}$/);
      expect(c.name.trim()).not.toBe("");
    }
    expect(COUNTRIES.length).toBeGreaterThan(150);
  });

  it("is sorted by name and offers every country's currency", () => {
    const names = COUNTRIES.map((c) => c.name);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
    for (const c of COUNTRIES) expect(CURRENCIES).toContain(c.currency);
    expect(new Set(CURRENCIES).size).toBe(CURRENCIES.length);
  });

  it("fills in the calling code and currency for a chosen country", () => {
    expect(countryByCode("GB")).toMatchObject({ calling: "44", currency: "GBP" });
    expect(countryByCode("KE")).toMatchObject({ calling: "254", currency: "KES" });
    expect(countryByCode("US")).toMatchObject({ calling: "1", currency: "USD" });
    expect(countryByCode("ZZ")).toBeUndefined();
  });
});
