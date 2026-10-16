import { describe, expect, it } from "vitest";

import { canStartAgain, countByStatus, currentStep, digits, isWorking } from "./logic";

describe("setup steps", () => {
  it("asks for the key first, then the number, then shows the connection", () => {
    expect(currentStep(false, undefined)).toBe(1);
    expect(currentStep(true, undefined)).toBe(2);
    expect(currentStep(true, "requested")).toBe(2);
    expect(currentStep(true, "failed")).toBe(2);
    expect(currentStep(true, "active")).toBe(3);
  });
  it("polls only while Lead Intel is working", () => {
    for (const s of ["requested", "awaiting_code", "connected"]) expect(isWorking(s)).toBe(true);
    for (const s of ["code_sent", "active", "failed", "cancelled", undefined]) expect(isWorking(s)).toBe(false);
  });
  it("lets the person start again only after an ending", () => {
    for (const s of [undefined, "failed", "cancelled", "disconnected"]) expect(canStartAgain(s)).toBe(true);
    for (const s of ["requested", "awaiting_code", "code_sent", "connected", "active"]) expect(canStartAgain(s)).toBe(false);
  });
});

describe("helpers", () => {
  it("keeps only digits", () => expect(digits("+254 712-345 678")).toBe("254712345678"));
  it("counts templates by status", () => {
    expect(countByStatus([{ status: "approved" }, { status: "approved" }, { status: "rejected" }])).toEqual({ draft: 0, submitted: 0, approved: 2, rejected: 1 });
  });
});
