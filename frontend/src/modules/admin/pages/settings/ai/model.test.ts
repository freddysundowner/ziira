import { describe, expect, it } from "vitest";

import { blockedReason, needsFreshConsent, parseLimit, tokens, usedPercent } from "./model";

describe("AI settings rules", () => {
  it("shows token counts with separators", () => {
    expect(tokens(2000000)).toBe("2,000,000");
    expect(tokens(1234.6)).toBe("1,235");
  });
  it("works out how much of the limit is used, never beyond 100", () => {
    expect(usedPercent(500, 2000)).toBe(25);
    expect(usedPercent(3000, 2000)).toBe(100);
    expect(usedPercent(0, 0)).toBe(100);
    expect(usedPercent(-5, 100)).toBe(0);
  });
  it("accepts only a whole number of tokens within bounds", () => {
    expect(parseLimit("1,500,000")).toBe(1500000);
    expect(parseLimit(" 0 ")).toBe(0);
    expect(parseLimit("1.5")).toBeNull();
    expect(parseLimit("abc")).toBeNull();
    expect(parseLimit("")).toBeNull();
    expect(parseLimit("3000000000")).toBeNull();
  });
  it("reads a refusal out of the log status", () => {
    expect(blockedReason("blocked:budget")).toBe("budget");
    expect(blockedReason("ok")).toBeNull();
  });
  it("asks for fresh consent only when it was given once and no longer holds", () => {
    const granted = [{ action: "granted" }] as never;
    expect(needsFreshConsent({ enabled: false, consent_valid: false, consents: granted })).toBe(true);
    expect(needsFreshConsent({ enabled: true, consent_valid: true, consents: granted })).toBe(false);
    expect(needsFreshConsent({ enabled: false, consent_valid: false, consents: [] as never })).toBe(false);
  });
});
