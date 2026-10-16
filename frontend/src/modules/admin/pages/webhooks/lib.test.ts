import { describe, expect, it } from "vitest";

import { canRedeliver, deliveryTone, endpointTone, eventSummary, groupEvents, toggleEvent } from "./lib";

describe("webhook helpers", () => {
  it("summarises events", () => {
    expect(eventSummary(["a", "b"])).toBe("a, b");
    expect(eventSummary(["a", "b", "c", "d", "e"])).toBe("a, b, c +2");
  });
  it("tones an endpoint by status and failures", () => {
    expect(endpointTone({ status: "active", consecutive_failures: 0 })).toBe("ok");
    expect(endpointTone({ status: "active", consecutive_failures: 2 })).toBe("warn");
    expect(endpointTone({ status: "paused", consecutive_failures: 0 })).toBe("neutral");
    expect(endpointTone({ status: "disabled", consecutive_failures: 0 })).toBe("bad");
  });
  it("tones deliveries", () => {
    expect(["delivered", "failed", "pending", "cancelled"].map(deliveryTone)).toEqual(["ok", "bad", "warn", "neutral"]);
  });
  it("lets only finished deliveries with content on active endpoints be sent again", () => {
    expect(canRedeliver({ status: "failed", has_body: true }, { status: "active" })).toBe(true);
    expect(canRedeliver({ status: "pending", has_body: true }, { status: "active" })).toBe(false);
    expect(canRedeliver({ status: "delivered", has_body: false }, { status: "active" })).toBe(false);
    expect(canRedeliver({ status: "failed", has_body: true }, { status: "disabled" })).toBe(false);
  });
  it("groups events by unit and toggles selections", () => {
    expect(groupEvents([{ unit: "pos", type: "sale.posted" }, { unit: "crm", type: "customer.created" }, { unit: "pos", type: "sale.returned" }])
      .map((g) => [g.unit, g.events.length])).toEqual([["crm", 1], ["pos", 2]]);
    expect(toggleEvent(["b"], "a", true)).toEqual(["a", "b"]);
    expect(toggleEvent(["a", "b"], "a", false)).toEqual(["b"]);
  });
});
