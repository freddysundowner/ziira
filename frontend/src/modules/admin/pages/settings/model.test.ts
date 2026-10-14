import { describe, expect, it } from "vitest";

import { sampleNumber, type Settings, toForm, toPatch } from "./model";

const base = {
  negative_stock_allowed: false, count_variance_threshold: "0", late_posting: "redirect", bill_match_tolerance_percent: "2",
  reminder_channel: "off", reminder_min_days_overdue: 1, reminder_repeat_days: 7, phone_country_code: "", weekend_days: ["sat", "sun"],
  payroll_unpaid_day_divisor: 30, overtime_multiplier: "1.5", overtime_hours_per_month: "173.33", receipt_footer: "Thanks", invoice_footer: "",
} as unknown as Settings;

describe("settings form", () => {
  it("turns every value into text", () => {
    const form = toForm(base);
    expect(form.weekend_days).toBe("sat,sun");
    expect(form.negative_stock_allowed).toBe("false");
    expect(form.reminder_repeat_days).toBe("7");
  });
  it("sends only what changed, with the right types", () => {
    const form = toForm(base);
    const patch = toPatch(form, { ...form, negative_stock_allowed: "true", reminder_repeat_days: "14", weekend_days: "fri", receipt_footer: " Hi " });
    expect(patch).toEqual({ negative_stock_allowed: true, reminder_repeat_days: 14, weekend_days: ["fri"], receipt_footer: "Hi" });
  });
  it("sends nothing when nothing changed", () => {
    const form = toForm(base);
    expect(toPatch(form, { ...form })).toEqual({});
  });
  it("previews a document number", () => {
    expect(sampleNumber("INV-", 42, 5)).toBe("INV-00042");
  });
});
