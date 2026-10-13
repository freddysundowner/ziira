import { expect, it } from "vitest";

import en from "./en.json";
import sw from "./sw.json";

function keys(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]);
}

it("the shell has the same English and Swahili keys", () => {
  expect(keys(sw).sort()).toEqual(keys(en).sort());
});
