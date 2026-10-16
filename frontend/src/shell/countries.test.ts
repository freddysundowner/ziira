import { describe, expect, it } from "vitest";

import { chooseCountries, COUNTRIES, countryByCode, CURRENCIES, currenciesOf, fromServer } from "./countries";

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

  it("uses the server's list (with its pack data) when it has one, else the static list", () => {
    const ke = fromServer({ code: "KE", name: "Kenya", calling: "254", currency: "KES", zone: "Africa/Nairobi", pack: "pack_ke", tax_id_label: "KRA PIN", tax_id_pattern: "^[AP]" });
    expect(ke).toMatchObject({ pack: "pack_ke", taxIdLabel: "KRA PIN" });
    expect(chooseCountries([ke])).toEqual([ke]);
    expect(chooseCountries(undefined)).toBe(COUNTRIES);
    expect(chooseCountries([])).toBe(COUNTRIES);
    expect(currenciesOf([ke, { ...ke, code: "TZ", currency: "TZS" }])).toEqual(["KES", "TZS"]);
  });
});
