import { describe, expect, it } from "vitest";

import { type Provider, providerBody } from "./ProviderCard";

const smtp = {
  name: "smtp", label: "SMTP", description: "", dns_hint: "", configured: true, missing: [], selected: false, tested_ok: false, updated_at: null, updated_by: null,
  fields: [
    { name: "host", label: "Server", secret: false, required: true, help: "", kind: "text", options: [], value: "mail.x.test", is_set: true },
    { name: "password", label: "Password", secret: true, required: false, help: "", kind: "text", options: [], value: null, is_set: true },
  ],
} as Provider;

describe("provider save body", () => {
  it("sends nothing when nothing changed, and never an empty secret", () => {
    expect(providerBody(smtp, { host: "mail.x.test" }, { password: "  " }, [])).toEqual({});
  });
  it("sends only changed plain fields, typed secrets and removals", () => {
    expect(providerBody(smtp, { host: "other.test" }, { password: "s3cret-value-123" }, [])).toEqual({ config: { host: "other.test" }, secrets: { password: "s3cret-value-123" } });
    expect(providerBody(smtp, { host: "mail.x.test" }, {}, ["password"])).toEqual({ clear_secrets: ["password"] });
  });
});
