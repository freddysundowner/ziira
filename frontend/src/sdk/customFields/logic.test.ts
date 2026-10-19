import { describe, expect, it } from "vitest";

import { type CustomFieldDef, displayValue, toFormValues, toPayload, validateCustomValues, visibleFields } from "./logic";

const def = (key: string, kind: CustomFieldDef["kind"], extra: Partial<CustomFieldDef> = {}): CustomFieldDef => ({
  id: key, company_id: null, entity_type: "products.product", key, label: key.toUpperCase(), kind, choices: [], required: false, searchable: false,
  sort_order: 0, active: true, source: "business", from_pack: false, ...extra,
});

describe("toFormValues", () => {
  it("turns saved values into text and missing ones into empty text", () => {
    const fields = [def("a", "text"), def("b", "bool"), def("c", "number"), def("d", "date")];
    expect(toFormValues(fields, { a: "x", b: false, c: "2.5" })).toEqual({ a: "x", b: "false", c: "2.5", d: "" });
  });
});

describe("validateCustomValues", () => {
  const fields = [def("n", "number"), def("d", "date"), def("r", "text", { required: true }), def("hidden", "text", { required: true, active: false })];
  it("flags a missing required field, a bad number and a bad date", () => {
    expect(validateCustomValues(fields, { n: "12a", d: "2026-02-31x", r: "" })).toEqual({ n: "number", d: "date", r: "required" });
  });
  it("accepts good values, negative and decimal numbers, and ignores hidden fields", () => {
    expect(validateCustomValues(fields, { n: "-3.25", d: "2026-02-28", r: " ok " })).toEqual({});
    expect(validateCustomValues(fields, { n: "", d: "", r: "x" })).toEqual({});
  });
});

describe("toPayload", () => {
  const fields = [def("a", "text"), def("b", "bool"), def("c", "number")];
  it("sends only what changed, clears with null and sends booleans as booleans", () => {
    expect(toPayload(fields, { a: "same", b: "true", c: "" }, { a: "same", b: "", c: "7" })).toEqual({ b: true, c: null });
  });
  it("sends nothing when nothing changed", () => {
    expect(toPayload(fields, { a: "x", b: "false", c: "1" }, { a: " x ", b: "false", c: "1" })).toEqual({});
  });
});

describe("visibleFields and displayValue", () => {
  it("lists active fields in order", () => {
    const list = [def("z", "text", { sort_order: 20 }), def("y", "text", { sort_order: 10 }), def("x", "text", { active: false })];
    expect(visibleFields(list).map((f) => f.key)).toEqual(["y", "z"]);
  });
  it("shows yes and no for booleans and nothing for an empty value", () => {
    expect(displayValue(def("b", "bool"), "true", "Yes", "No")).toBe("Yes");
    expect(displayValue(def("b", "bool"), "false", "Yes", "No")).toBe("No");
    expect(displayValue(def("t", "text"), "", "Yes", "No")).toBe("");
    expect(displayValue(def("t", "text"), "hi", "Yes", "No")).toBe("hi");
  });
});
