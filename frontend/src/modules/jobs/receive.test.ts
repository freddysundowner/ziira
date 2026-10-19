import { describe, expect, it } from "vitest";

import { buildJobBody, emptyReceive, receiveProblems } from "./receive";

describe("receiving an item", () => {
  it("needs a title and a branch", () => {
    expect(receiveProblems(emptyReceive())).toEqual(["title", "branch"]);
    expect(receiveProblems({ ...emptyReceive("b1"), title: "Brakes" })).toEqual([]);
  });
  it("needs a name for a new item once identifiers are typed", () => {
    const form = { ...emptyReceive("b1"), title: "x", itemMode: "new" as const, newRows: [{ name: "plate", value: "KAA 1" }] };
    expect(receiveProblems(form)).toEqual(["newLabel"]);
  });
  it("sends a chosen customer as an id only, and an unknown one as name and phone", () => {
    const known = buildJobBody("c1", { ...emptyReceive("b1"), title: " Brakes ", customerId: "u1", customerName: "ignored" });
    expect(known).toMatchObject({ title: "Brakes", customer_id: "u1", customer_name: null, customer_phone: null });
    const walkIn = buildJobBody("c1", { ...emptyReceive("b1"), title: "x", customerName: " Amina ", customerPhone: "" });
    expect(walkIn).toMatchObject({ customer_id: null, customer_name: "Amina", customer_phone: null });
  });
  it("sends a new item with its cleaned identifiers, or an existing one by id", () => {
    const made = buildJobBody("c1", { ...emptyReceive("b1"), title: "x", itemMode: "new", newLabel: "Corolla", newKind: "", newRows: [{ name: "plate", value: " KAA 1 " }, { name: "", value: "" }] });
    expect(made.new_asset).toEqual({ label: "Corolla", kind: "item", identifiers: { plate: "KAA 1" } });
    expect(made.asset_id).toBeNull();
    const old = buildJobBody("c1", { ...emptyReceive("b1"), title: "x", assetId: "a1", newLabel: "left over" });
    expect(old).toMatchObject({ asset_id: "a1", new_asset: null });
  });
  it("sends the checklist lines that have text", () => {
    expect(buildJobBody("c1", { ...emptyReceive("b1"), title: "x", checklist: ["Lights", " ", "Tyres"] }).checklist_items).toEqual(["Lights", "Tyres"]);
    expect(buildJobBody("c1", { ...emptyReceive("b1"), title: "x" }).checklist_items).toBeNull();
  });
});
