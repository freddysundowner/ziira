/** The coupon form (text), what is wrong with it, and the request the API takes. Percent or fixed amounts per currency. */
import { dateToIso } from "./format";

export const COUPON_CODE = /^[A-Z0-9][A-Z0-9_-]{2,39}$/;

export interface AmountRow {
  currency: string;
  amount: string;
}

export interface CouponForm {
  code: string;
  description: string;
  kind: "percent" | "fixed";
  percent: string;
  amounts: AmountRow[];
  duration: "once" | "repeating" | "forever";
  periods: string;
  max: string;
  expires: string;
  plans: string[];
}

export const emptyCouponForm = (): CouponForm => ({
  code: "", description: "", kind: "percent", percent: "", amounts: [{ currency: "", amount: "" }], duration: "once", periods: "", max: "", expires: "", plans: [],
});

/** Field -> a key under "plans.coupons.errors". */
export function couponProblems(f: CouponForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!COUPON_CODE.test(f.code.trim())) errors.code = "code";
  if (f.kind === "percent") {
    const p = Number(f.percent);
    if (!f.percent.trim() || !Number.isFinite(p) || p <= 0 || p > 100) errors.percent = "percent";
  } else {
    const rows = f.amounts.filter((r) => r.currency.trim() || r.amount.trim());
    const currencies = rows.map((r) => r.currency.trim().toUpperCase());
    if (rows.length === 0 || rows.some((r) => !/^[A-Za-z]{3}$/.test(r.currency.trim()) || !/^\d+(\.\d{1,2})?$/.test(r.amount.trim()) || Number(r.amount) <= 0)) errors.amounts = "amounts";
    else if (new Set(currencies).size !== currencies.length) errors.amounts = "duplicate";
  }
  if (f.duration === "repeating") {
    const n = Number(f.periods);
    if (!Number.isInteger(n) || n < 1 || n > 120) errors.periods = "periods";
  }
  if (f.max.trim() && !(Number.isInteger(Number(f.max)) && Number(f.max) >= 1)) errors.max = "max";
  return errors;
}

export function toCouponIn(f: CouponForm) {
  const amounts: Record<string, string> = {};
  if (f.kind === "fixed") for (const r of f.amounts) if (r.currency.trim()) amounts[r.currency.trim().toUpperCase()] = r.amount.trim();
  return {
    code: f.code.trim().toUpperCase(),
    description: f.description.trim(),
    percent_off: f.kind === "percent" ? f.percent.trim() : null,
    amounts,
    duration: f.duration,
    duration_periods: f.duration === "repeating" ? Number(f.periods) : null,
    max_redemptions: f.max.trim() ? Number(f.max) : null,
    expires_at: dateToIso(f.expires),
    plan_codes: f.plans,
  };
}
