import { describe, expect, it } from "vitest";

import { MIN_PASSWORD, passwordProblem, passwordReady } from "./password";

const form = (current: string, next: string, repeat: string) => ({ current, next, repeat });
const long = "a".repeat(MIN_PASSWORD);

describe("the change-password form", () => {
  it("is not a problem while fields are empty", () => {
    expect(passwordProblem(form("", "", ""))).toBeNull();
    expect(passwordReady(form("", "", ""))).toBe(false);
  });
  it("wants a long enough new password", () => {
    expect(passwordProblem(form("old", "short", ""))).toBe("short");
    expect(passwordProblem(form("old", "a".repeat(MIN_PASSWORD - 1), ""))).toBe("short");
    expect(passwordProblem(form("old", long, ""))).toBeNull();
  });
  it("wants a different password and the same one twice", () => {
    expect(passwordProblem(form(long, long, ""))).toBe("same");
    expect(passwordProblem(form("old", long, "other"))).toBe("mismatch");
  });
  it("is ready only when everything fits", () => {
    expect(passwordReady(form("old", long, long))).toBe(true);
    expect(passwordReady(form("", long, long))).toBe(false);
    expect(passwordReady(form("old", long, ""))).toBe(false);
  });
});
