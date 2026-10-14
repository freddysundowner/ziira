import { describe, expect, it } from "vitest";

import { buildPayload, isComplete, PROVIDERS, providersFor } from "./providers";

const smtp = PROVIDERS.find((p) => p.id === "smtp")!;

describe("messaging providers", () => {
  it("lists providers by channel", () => {
    expect(providersFor("sms").map((p) => p.id)).toEqual(["blessedtexts", "africastalking"]);
    expect(providersFor("email").length).toBe(4);
  });
  it("splits secret from settings and types the values", () => {
    const { secret, config } = buildPayload(smtp, { host: "mail.example.com", port: "465", username: "", password: "pw", from_address: "a@b.co", starttls: "false" });
    expect(secret).toEqual({ host: "mail.example.com", port: 465, password: "pw" });
    expect(config).toEqual({ from_address: "a@b.co", starttls: false });
  });
  it("needs the required fields", () => {
    expect(isComplete(smtp, { host: "h" })).toBe(false);
    expect(isComplete(smtp, { host: "h", from_address: "a@b.co" })).toBe(true);
  });
});
