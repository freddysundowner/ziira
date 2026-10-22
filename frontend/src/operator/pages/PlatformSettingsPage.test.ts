import { describe, expect, it } from "vitest";

import { addressWarning } from "./PlatformSettingsPage";

describe("address warnings on Platform > Settings", () => {
  it("warns when the app and the website are the same address, ignoring case and a trailing slash", () => {
    expect(addressWarning("https://app.example.com", "https://APP.example.com/")).toBe("same");
  });
  it("warns when the website address is empty", () => {
    expect(addressWarning("https://app.example.com", "")).toBe("empty");
    expect(addressWarning("https://app.example.com", undefined)).toBe("empty");
  });
  it("stays quiet when they differ", () => {
    expect(addressWarning("https://app.example.com", "https://example.com")).toBeNull();
  });
});
