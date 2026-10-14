import { describe, expect, it } from "vitest";

import people from "./module";

const keys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]));

describe("people module", () => {
  it("has the same English and Swahili keys", () => {
    expect(keys(people.translations!.sw).sort()).toEqual(keys(people.translations!.en).sort());
  });
  it("gives every page a permission and every menu entry a group", () => {
    expect((people.routes ?? []).filter((r) => !r.permission)).toEqual([]);
    expect((people.menu ?? []).filter((m) => m.group !== "people")).toEqual([]);
  });
});
