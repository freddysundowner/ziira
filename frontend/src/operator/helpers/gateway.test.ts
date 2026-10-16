import { describe, expect, it } from "vitest";

import { canMarkPaid, gatewayBody, gatewayDirty, gatewayDraft, parseCodes, type Gateway } from "./gateway";

const gateway = {
  name: "x", enabled: false, default_for: ["KES"],
  fields: [
    { name: "base_url", label: "", secret: false, required: true, help: "", value: "https://a.test", is_set: true },
    { name: "api_key", label: "", secret: true, required: true, help: "", value: null, is_set: true },
  ],
} as unknown as Gateway;

describe("gateway form", () => {
  it("starts clean and sends nothing", () => {
    const d = gatewayDraft(gateway);
    expect(gatewayDirty(gateway, d)).toBe(false);
    expect(gatewayBody(gateway, d)).toEqual({});
  });
  it("sends only what changed and never an empty secret", () => {
    const d = { ...gatewayDraft(gateway), enabled: true, values: { base_url: "https://b.test" }, secrets: { api_key: "  " }, defaultFor: "kes, ke" };
    expect(gatewayBody(gateway, d)).toEqual({ enabled: true, config: { base_url: "https://b.test" }, default_for: ["KES", "KE"] });
  });
  it("sends a typed secret once, and a removal by name", () => {
    expect(gatewayBody(gateway, { ...gatewayDraft(gateway), secrets: { api_key: "sp_new" } })).toEqual({ secrets: { api_key: "sp_new" } });
    expect(gatewayBody(gateway, { ...gatewayDraft(gateway), cleared: ["api_key"] })).toEqual({ clear_secrets: ["api_key"] });
  });
  it("reads code lists", () => {
    expect(parseCodes("kes; KE ,ke")).toEqual(["KES", "KE"]);
    expect(parseCodes("")).toEqual([]);
  });
  it("lets an operator settle anything not yet credited", () => {
    expect(canMarkPaid("mismatch")).toBe(true);
    expect(canMarkPaid("completed")).toBe(false);
  });
});
