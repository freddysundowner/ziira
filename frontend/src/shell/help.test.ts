import { describe, expect, it, vi } from "vitest";

describe("help links", () => {
  it("builds addresses from VITE_HELP_URL and drops a trailing slash", async () => {
    vi.stubEnv("VITE_HELP_URL", "https://ziira.example/help/");
    vi.resetModules();
    const { helpUrl } = await import("./help");
    expect(helpUrl()).toBe("https://ziira.example/help/");
    expect(helpUrl("sell/set-opening-stock")).toBe("https://ziira.example/help/sell/set-opening-stock/");
    expect(helpUrl("/sell/set-opening-stock/")).toBe("https://ziira.example/help/sell/set-opening-stock/");
    vi.unstubAllEnvs();
  });

  it("returns nothing when it is not set, so the link stays hidden", async () => {
    vi.stubEnv("VITE_HELP_URL", "");
    vi.resetModules();
    const { helpUrl } = await import("./help");
    expect(helpUrl()).toBeUndefined();
    expect(helpUrl("sell/set-opening-stock")).toBeUndefined();
    vi.unstubAllEnvs();
  });

  it("maps every checklist step of the editions to a guide path with two parts", async () => {
    const { GUIDE_FOR_STEP } = await import("./help");
    for (const path of Object.values(GUIDE_FOR_STEP)) expect(path).toMatch(/^[a-z-]+\/[a-z-]+$/);
  });
});
