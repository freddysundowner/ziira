import { describe, expect, it } from "vitest";

import { blankLine, estimateTone, linesReady, toLineBodies } from "./estimateForm";

describe("estimate lines", () => {
  it("are ready when each has a quantity and a name or product, and there is at least one", () => {
    expect(linesReady([])).toBe(false);
    expect(linesReady([blankLine()])).toBe(false);
    expect(linesReady([{ ...blankLine(), description: "Brake pads" }])).toBe(true);
    expect(linesReady([{ ...blankLine(), productId: "p1", quantity: "0" }])).toBe(false);
    expect(linesReady([{ ...blankLine("labour"), description: "Fit" }, { ...blankLine(), productId: "p1" }])).toBe(true);
  });
  it("make the request body, leaving a blank price to the server", () => {
    expect(toLineBodies([{ kind: "part", productId: "p1", description: " ", quantity: "2", unitPrice: "" }])).toEqual([
      { kind: "part", description: null, quantity: "2", unit_price: null, product_id: "p1" }]);
    expect(toLineBodies([{ kind: "labour", productId: "p1", description: "Fit", quantity: "1.5", unitPrice: "800" }])[0]).toMatchObject({ product_id: null, unit_price: "800" });
  });
  it("colours each status", () => {
    expect(estimateTone("approved")).toBe("ok");
    expect(estimateTone("unknown")).toBe("neutral");
  });
});
