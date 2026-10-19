import { describe, expect, it } from "vitest";

import { groupByEntity, keyFromLabel, moved, parseChoices, type EntityRow, type FieldRow } from "./lib";

describe("keyFromLabel", () => {
  it("makes a safe key from a name", () => {
    expect(keyFromLabel("Hair type")).toBe("hair_type");
    expect(keyFromLabel("  Vehicle plate (no.) ")).toBe("vehicle_plate_no");
    expect(keyFromLabel("Café")).toBe("cafe");
  });
  it("starts with a letter and stays within 40 characters", () => {
    expect(keyFromLabel("2nd visit")).toBe("f_2nd_visit");
    expect(keyFromLabel("x".repeat(60)).length).toBe(40);
    expect(keyFromLabel("???")).toBe("");
  });
});

describe("parseChoices", () => {
  it("trims, drops blanks and repeats", () => {
    expect(parseChoices(" Junior\n\nSenior \nJunior\n")).toEqual(["Junior", "Senior"]);
  });
});

describe("moved", () => {
  it("swaps with the neighbour and stays put at the ends", () => {
    expect(moved(["a", "b", "c"], "b", -1)).toEqual(["b", "a", "c"]);
    expect(moved(["a", "b", "c"], "b", 1)).toEqual(["a", "c", "b"]);
    expect(moved(["a", "b", "c"], "a", -1)).toEqual(["a", "b", "c"]);
    expect(moved(["a", "b", "c"], "c", 1)).toEqual(["a", "b", "c"]);
    expect(moved(["a"], "zzz", 1)).toEqual(["a"]);
  });
});

describe("groupByEntity", () => {
  const entities = [{ entity_type: "a.x", label: "X" }, { entity_type: "b.y", label: "Y" }] as EntityRow[];
  const f = (id: string, entity_type: string, sort_order: number) => ({ id, entity_type, sort_order, label: id }) as FieldRow;
  it("groups in order and keeps empty groups", () => {
    const groups = groupByEntity(entities, [f("two", "a.x", 20), f("one", "a.x", 10)]);
    expect(groups.map((g) => g.fields.map((x) => x.id))).toEqual([["one", "two"], []]);
  });
});
