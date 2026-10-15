import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import sw from "../i18n/sw.json";
import { describeWarning } from "./warnings";

// the codes the server's sale posting can send with an accepted sale (ziira/modules/pos/services/sales.py, credit.py)
const SERVER_CODES = ["price_changed", "closed_day", "till_closed", "mobile_money_without_code", "unauthorised_override", "over_credit_limit", "customer_on_hold"];

describe("what the server says about an accepted sale", () => {
  const t = (key: string, o?: Record<string, unknown>) => `${key}|${o?.detail ?? ""}|${o?.defaultValue ?? ""}`;
  it("is looked up by its code, with the rest as detail", () => {
    expect(describeWarning("price_changed:CEM:116:120", t)).toMatch(/^terminal\.sync\.warning\.price_changed\|CEM 116 120\|/);
    expect(describeWarning("closed_day", t)).toMatch(/^terminal\.sync\.warning\.closed_day\|\|/);
  });
  it("falls back to plain words for a code it does not know", () => {
    expect(describeWarning("brand_new_thing:x", t)).toContain("Brand new thing x");
  });
  it("has a sentence in English and Swahili for every code the server can send", () => {
    for (const code of SERVER_CODES) {
      expect((en.sync.warning as Record<string, string>)[code], code).toBeTruthy();
      expect((sw.sync.warning as Record<string, string>)[code], code).toBeTruthy();
    }
  });
});
