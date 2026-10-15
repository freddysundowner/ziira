import { describe, expect, it } from "vitest";

import { describeConditions, editableFields, fieldsOf, serverMessage, toDraft, toValues, validate } from "./schema";

const schema = {
  properties: {
    quantity: { type: "number", title: "Quantity to order", minimum: 1, maximum: 1000 },
    pieces: { type: "integer", title: "Pieces" },
    note: { type: "string", title: "Note", max_length: 5 },
    kind: { type: "string", title: "Kind", enum: ["a", "b"] },
    on: { type: "date", title: "On" },
    supplier_id: { type: "uuid", title: "Supplier" },
    fixed: { type: "string", title: "Fixed", editable: false },
    urgent: { type: "boolean", title: "Urgent" },
  },
  required: ["quantity"],
};
const fields = fieldsOf(schema);

describe("fieldsOf", () => {
  it("reads titles, limits, options and required", () => {
    expect(fields.map((f) => f.name)).toEqual(["quantity", "pieces", "note", "kind", "on", "supplier_id", "fixed", "urgent"]);
    expect(fields[0]).toMatchObject({ type: "number", minimum: 1, maximum: 1000, required: true, editable: true });
    expect(fields[3].options).toEqual(["a", "b"]);
    expect(fields[6].editable).toBe(false);
  });
  it("copes with no schema", () => {
    expect(fieldsOf(undefined)).toEqual([]);
    expect(fieldsOf({})).toEqual([]);
  });
});

describe("editableFields", () => {
  it("drops fixed fields and ids, keeping the branch only when asked", () => {
    expect(editableFields(fields).map((f) => f.name)).not.toContain("fixed");
    expect(editableFields(fields).map((f) => f.name)).not.toContain("supplier_id");
    const withBranch = fieldsOf({ properties: { branch_id: { type: "uuid", title: "Branch" } } });
    expect(editableFields(withBranch)).toEqual([]);
    expect(editableFields(withBranch, true)).toHaveLength(1);
  });
});

describe("validate", () => {
  it("flags missing required values", () => {
    expect(validate(fields, { quantity: " " }).quantity).toEqual({ code: "required" });
  });
  it("checks numbers, ranges, options, dates and length", () => {
    expect(validate(fields, { quantity: "abc" }).quantity.code).toBe("number");
    expect(validate(fields, { quantity: "0" }).quantity).toEqual({ code: "min", limit: "1" });
    expect(validate(fields, { quantity: "1001" }).quantity).toEqual({ code: "max", limit: "1000" });
    expect(validate(fields, { quantity: "5", pieces: "1.5" }).pieces.code).toBe("whole");
    expect(validate(fields, { quantity: "5", kind: "z" }).kind.code).toBe("option");
    expect(validate(fields, { quantity: "5", on: "01/02/2026" }).on.code).toBe("date");
    expect(validate(fields, { quantity: "5", note: "toolong" }).note).toEqual({ code: "length", limit: "5" });
  });
  it("accepts good values", () => {
    expect(validate(fields, { quantity: "12.50", pieces: "3", kind: "a", on: "2026-01-02" })).toEqual({});
  });
});

describe("toValues and toDraft", () => {
  it("round-trips, sending whole numbers as numbers and decimals as text, leaving empties out", () => {
    const draft = toDraft(fields, { quantity: "12.50", pieces: 3, urgent: true });
    expect(draft).toMatchObject({ quantity: "12.50", pieces: "3", urgent: "true", note: "" });
    expect(toValues(fields, draft)).toEqual({ quantity: "12.50", pieces: 3, urgent: true });
  });
});

describe("describeConditions", () => {
  const w = { yes: "Yes", no: "No", branchName: (id: string) => (id === "b1" ? "Main" : undefined) };
  const rule = fieldsOf({ properties: { branch_id: { type: "uuid", title: "Branch" }, max_amount: { type: "number", title: "Largest amount" }, only: { type: "boolean", title: "Only overdue" } } });
  it("writes one phrase per condition that has a value", () => {
    expect(describeConditions(rule, { branch_id: "b1", max_amount: "5000", only: false }, w)).toEqual(["Branch: Main", "Largest amount: 5000", "Only overdue: No"]);
    expect(describeConditions(rule, {}, w)).toEqual([]);
  });
  it("uses the caller's wording for special fields", () => {
    expect(describeConditions(rule, { max_amount: "5000" }, { ...w, special: (f, v) => (f.name === "max_amount" ? `KES ${String(v)}` : undefined) })).toEqual(["Largest amount: KES 5000"]);
  });
});

describe("serverMessage", () => {
  it("finds a field's message under any of the keys", () => {
    expect(serverMessage({ "params.quantity": "too big" }, "quantity")).toBe("too big");
    expect(serverMessage({ "conditions.max_amount": "bad" }, "max_amount")).toBe("bad");
    expect(serverMessage({}, "x")).toBeUndefined();
  });
});
