import { describe, expect, it } from "vitest";

import { couponProblems, emptyCouponForm, toCouponIn } from "./coupon";

const percent = () => ({ ...emptyCouponForm(), code: "WELCOME10", percent: "10" });

describe("coupon form", () => {
  it("accepts a percent coupon", () => {
    expect(couponProblems(percent())).toEqual({});
  });
  it("needs a capital code of at least three characters", () => {
    expect(couponProblems({ ...percent(), code: "ab" }).code).toBe("code");
    expect(couponProblems({ ...percent(), code: "welcome" }).code).toBe("code");
  });
  it("keeps a percent above zero and at most 100", () => {
    expect(couponProblems({ ...percent(), percent: "0" }).percent).toBe("percent");
    expect(couponProblems({ ...percent(), percent: "101" }).percent).toBe("percent");
    expect(couponProblems({ ...percent(), percent: "12.5" })).toEqual({});
  });
  it("needs a clean amount for each currency of a fixed coupon, and no currency twice", () => {
    const fixed = { ...percent(), kind: "fixed" as const };
    expect(couponProblems(fixed).amounts).toBe("amounts");
    expect(couponProblems({ ...fixed, amounts: [{ currency: "usd", amount: "5" }, { currency: "KES", amount: "500.50" }] })).toEqual({});
    expect(couponProblems({ ...fixed, amounts: [{ currency: "usd", amount: "5" }, { currency: "USD", amount: "6" }] }).amounts).toBe("duplicate");
    expect(couponProblems({ ...fixed, amounts: [{ currency: "usd", amount: "0" }] }).amounts).toBe("amounts");
  });
  it("needs the number of periods only for a repeating discount", () => {
    expect(couponProblems({ ...percent(), duration: "repeating" }).periods).toBe("periods");
    expect(couponProblems({ ...percent(), duration: "repeating", periods: "3" })).toEqual({});
    expect(couponProblems({ ...percent(), duration: "once", periods: "" })).toEqual({});
  });
  it("sends only what applies", () => {
    expect(toCouponIn({ ...percent(), code: " welcome10 ", max: "50", plans: ["pro"] })).toMatchObject({
      code: "WELCOME10", percent_off: "10", amounts: {}, duration: "once", duration_periods: null, max_redemptions: 50, plan_codes: ["pro"],
    });
    const fixed = toCouponIn({ ...percent(), kind: "fixed", amounts: [{ currency: "usd", amount: "5" }, { currency: "", amount: "" }], duration: "repeating", periods: "6" });
    expect(fixed).toMatchObject({ percent_off: null, amounts: { USD: "5" }, duration_periods: 6 });
  });
});
