import { describe, expect, it } from "vitest";

import { fieldValues, missingRequired, offeredProviders, type ProviderField, type ProviderInfo } from "./usePaymentProviders";

const field = (over: Partial<ProviderField>): ProviderField => ({ key: "k", label: "K", secret: false, required: true, kind: "text", options: [], default: null, help: "", ...over });
const provider = (name: string, development_only = false): ProviderInfo => ({ name, title: name.toUpperCase(), development_only, supports_prompts: true, credential_fields: [], config_fields: [] });

describe("provider forms", () => {
  it("sends only the fields that have a value, using a field's default when nothing was typed", () => {
    const fields = [field({ key: "a" }), field({ key: "b", required: false }), field({ key: "c", required: false, default: "paybill" })];
    expect(fieldValues(fields, { a: " 1 ", b: "  " })).toEqual({ a: "1", c: "paybill" });
  });

  it("finds the first required field left empty", () => {
    const fields = [field({ key: "a", label: "A" }), field({ key: "b", label: "B" }), field({ key: "c", required: false })];
    expect(missingRequired(fields, { a: "x" })?.label).toBe("B");
    expect(missingRequired(fields, { a: "x", b: "y" })).toBeUndefined();
  });

  it("offers real providers before development-only ones", () => {
    expect(offeredProviders([provider("zz", true), provider("b"), provider("a")]).map((p) => p.name)).toEqual(["a", "b", "zz"]);
  });
});
