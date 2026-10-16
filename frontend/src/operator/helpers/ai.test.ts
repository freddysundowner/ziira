import { describe, expect, it } from "vitest";

import { barPercent, maskedKey, providerBody, providerDirty, providerDraft, usd, type AiProvider } from "./ai";

const provider = {
  name: "p", enabled: false, base_url: "", key_set: true, key_last4: "1234", terms_ack_at: null,
  models: { explain: "a", rank: "a", ask: "b" },
} as unknown as AiProvider;

describe("AI provider drafts", () => {
  it("send nothing when nothing changed", () => {
    expect(providerBody(provider, providerDraft(provider))).toEqual({});
    expect(providerDirty(provider, providerDraft(provider))).toBe(false);
  });
  it("send only what changed, and a key only when typed", () => {
    const d = { ...providerDraft(provider), enabled: true, apiKey: "  secret-key-0001  ", models: { explain: "a", rank: "c", ask: "b" } };
    expect(providerBody(provider, d)).toEqual({ enabled: true, api_key: "secret-key-0001", models: { rank: "c" } });
  });
  it("sends the acknowledgement as a change in either direction", () => {
    expect(providerBody(provider, { ...providerDraft(provider), termsAcknowledged: true })).toEqual({ terms_acknowledged: true });
  });
});

describe("AI display helpers", () => {
  it("shows only the last four characters of a key", () => expect(maskedKey("1234")).toBe("····1234"));
  it("writes money with enough places", () => {
    expect(usd("0.1")).toBe("$0.10");
    expect(usd("0.0004")).toBe("$0.0004");
    expect(usd(null)).toBe("—");
  });
  it("sizes day bars against the busiest day", () => {
    expect(barPercent("5", 10)).toBe(50);
    expect(barPercent("0", 10)).toBe(2);
    expect(barPercent("1", 0)).toBe(0);
  });
});
