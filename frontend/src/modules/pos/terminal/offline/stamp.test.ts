import { afterEach, describe, expect, it } from "vitest";

import { setDisplayTimeZone } from "@/sdk";

import { stamp } from "./localSale";

afterEach(() => setDisplayTimeZone(undefined));

describe("the offline receipt time", () => {
  it("is on the company's clock, the same as the server's receipt", () => {
    setDisplayTimeZone("Africa/Nairobi");
    expect(stamp(Date.parse("2026-03-04T21:30:00Z"))).toBe("2026-03-05 00:30");
    setDisplayTimeZone("America/New_York");
    expect(stamp(Date.parse("2026-03-04T21:30:00Z"))).toBe("2026-03-04 16:30");
  });
});
