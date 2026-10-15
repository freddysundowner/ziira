import { describe, expect, it } from "vitest";

import {
  afterAttempt, bySeq, chipOf, count, expired, LARGE_QUEUE, nextToSend, OLD_AFTER_MS, outboxWarnings, outcomeOf, provisionalNumber, reservedQuantities,
  RETRY_BASE_MS, RETRY_MAX_MS, retryDelay, retryNow,
} from "./outbox";
import { entry } from "./testing";

describe("retry schedule", () => {
  it("doubles from 5 seconds up to 5 minutes", () => {
    expect([1, 2, 3, 4, 5, 6, 7, 8].map((n) => retryDelay(n))).toEqual([5000, 10000, 20000, 40000, 80000, 160000, 300000, 300000]);
    expect(retryDelay(1)).toBe(RETRY_BASE_MS);
    expect(retryDelay(50)).toBe(RETRY_MAX_MS);
  });
  it("spreads tills apart with jitter of at most a quarter, and never waits less than the base", () => {
    expect(retryDelay(1, 1)).toBe(6250);
    expect(retryDelay(1, 5)).toBe(6250);
    expect(retryDelay(1, -1)).toBe(5000);
    expect(retryDelay(0)).toBe(5000);
  });
});

describe("order", () => {
  it("sends the oldest waiting sale first, whatever order the list comes in", () => {
    const list = [entry({ seq: 3 }), entry({ seq: 1 }), entry({ seq: 2 })];
    expect(bySeq(list).map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(nextToSend(list, 10)?.seq).toBe(1);
  });
  it("holds later sales back while an earlier one waits for its retry", () => {
    const list = [entry({ seq: 1, nextAttemptAt: 5000 }), entry({ seq: 2 })];
    expect(nextToSend(list, 1000)).toBeUndefined();
    expect(nextToSend(list, 5000)?.seq).toBe(1);
  });
  it("passes over sales the server refused and sales already sent", () => {
    const list = [entry({ seq: 1, state: "failed" }), entry({ seq: 2, state: "done" }), entry({ seq: 3 })];
    expect(nextToSend(list, 0)?.seq).toBe(3);
    expect(nextToSend([entry({ seq: 1, state: "done" })], 0)).toBeUndefined();
  });
  it("picks up a sale left 'sending' by a page that closed", () => {
    expect(nextToSend([entry({ seq: 1, state: "sending" })], 0)?.seq).toBe(1);
  });
});

describe("the answer to a sent sale", () => {
  const ok = (status: string, extra: object = {}) => outcomeOf(200, { results: [{ status, number: "POS-HQ-D1-000123", id: "s1", warnings: [], ...extra }] });
  it("accepts ok and duplicate (a retry the server had already recorded)", () => {
    expect(ok("ok")).toEqual({ kind: "accepted", number: "POS-HQ-D1-000123", saleId: "s1", warnings: [], duplicate: false });
    expect(ok("duplicate")).toMatchObject({ kind: "accepted", duplicate: true });
  });
  it("keeps the server's warnings to show later", () => {
    expect(ok("ok", { warnings: ["price_changed:CEM:116:120"] })).toMatchObject({ warnings: ["price_changed:CEM:116:120"] });
  });
  it("a sale the server read and refused needs attention, with its reason", () => {
    expect(ok("rejected", { error: "Product not found" })).toEqual({ kind: "rejected", reason: "Product not found" });
    expect(outcomeOf(200, { results: [{ status: "rejected" }] })).toMatchObject({ kind: "rejected" });
  });
  it("no answer worth trusting is retried, never failed: network, server trouble, signed out, too many requests", () => {
    for (const status of [0, 401, 408, 429, 500, 502, 503, 504]) expect(outcomeOf(status, { message: "x" }).kind).toBe("retry");
    expect(outcomeOf(200, {}).kind).toBe("retry");
    expect(outcomeOf(200, null).kind).toBe("retry");
  });
  it("a request the server refuses as a whole needs attention", () => {
    expect(outcomeOf(422, { message: "bad" })).toEqual({ kind: "rejected", reason: "bad" });
    expect(outcomeOf(403, { message: "A device key is required" }).kind).toBe("rejected");
    expect(outcomeOf(409, undefined).kind).toBe("rejected");
  });
});

describe("what happens to an entry after an attempt", () => {
  it("accepted: done, with the server's number and warnings", () => {
    const patch = afterAttempt(entry({ attempts: 2 }), { kind: "accepted", number: "N1", saleId: "s", warnings: ["closed_day"], duplicate: false }, 9000);
    expect(patch).toMatchObject({ state: "done", doneAt: 9000, serverNumber: "N1", saleId: "s", warnings: ["closed_day"], lastError: "", attempts: 3 });
  });
  it("refused: failed, kept with the reason", () => {
    expect(afterAttempt(entry(), { kind: "rejected", reason: "No stock" }, 5)).toMatchObject({ state: "failed", lastError: "No stock", attempts: 1 });
  });
  it("no answer: back to pending with a later time, longer each time", () => {
    const first = afterAttempt(entry({ attempts: 0 }), { kind: "retry", reason: "offline" }, 1000);
    expect(first).toMatchObject({ state: "pending", nextAttemptAt: 6000, attempts: 1, lastError: "offline" });
    expect(afterAttempt(entry({ attempts: 2 }), { kind: "retry", reason: "offline" }, 1000)).toMatchObject({ nextAttemptAt: 1000 + 20000, attempts: 3 });
  });
  it("a refused sale put back by hand starts again at once", () => {
    expect(retryNow(77)).toEqual({ state: "pending", attempts: 0, nextAttemptAt: 77, lastError: "" });
  });
});

describe("the status chip", () => {
  const c = (over: object) => ({ waiting: 0, sending: 0, attention: 0, done: 0, ...over });
  it("says online when nothing waits", () => expect(chipOf(c({}), true)).toEqual({ kind: "online", n: 0 }));
  it("says offline, with what waits", () => expect(chipOf(c({ waiting: 2 }), false)).toEqual({ kind: "offline", n: 2 }));
  it("says syncing while a sale is being sent", () => expect(chipOf(c({ waiting: 3, sending: 1 }), true)).toEqual({ kind: "syncing", n: 3 }));
  it("says waiting when connected but not yet sending", () => expect(chipOf(c({ waiting: 3 }), true)).toEqual({ kind: "waiting", n: 3 }));
  it("sales needing attention come first, online or not", () => {
    expect(chipOf(c({ waiting: 3, attention: 1 }), true)).toEqual({ kind: "attention", n: 1 });
    expect(chipOf(c({ attention: 2 }), false)).toEqual({ kind: "attention", n: 2 });
  });
  it("counts entries by state", () => {
    const list = [entry({ seq: 1 }), entry({ seq: 2, state: "sending" }), entry({ seq: 3, state: "failed" }), entry({ seq: 4, state: "done" })];
    expect(count(list)).toEqual({ waiting: 2, sending: 1, attention: 1, done: 1 });
  });
});

describe("warnings about the queue", () => {
  it("warns when a sale has waited more than a day", () => {
    expect(outboxWarnings([entry({ madeAt: 0 })], OLD_AFTER_MS + 1)).toEqual(["old"]);
    expect(outboxWarnings([entry({ madeAt: 0 })], OLD_AFTER_MS)).toEqual([]);
    expect(outboxWarnings([entry({ madeAt: 0, state: "done" })], OLD_AFTER_MS * 3)).toEqual([]);
  });
  it("warns when the queue is large", () => {
    const many = Array.from({ length: LARGE_QUEUE }, (_, i) => entry({ seq: i + 1, madeAt: 100 }));
    expect(outboxWarnings(many, 200)).toEqual(["large"]);
    expect(outboxWarnings(many.slice(1), 200)).toEqual([]);
  });
});

describe("stock not yet taken at the server", () => {
  it("adds up the quantities of sales still waiting at this branch", () => {
    const two = entry({ seq: 2, op: { ...entry().op, lines: [{ product_id: "p1", quantity: "2.5", discount: 0 }, { product_id: "p2", quantity: "1", discount: 0 }] } });
    const reserved = reservedQuantities([entry({ seq: 1 }), two, entry({ seq: 3, state: "failed" }), entry({ seq: 4, state: "done" }), entry({ seq: 5, branchId: "other" })], "branch-1");
    expect(reserved.get("p1")).toBe(3.5);
    expect(reserved.get("p2")).toBe(1);
  });
});

describe("keeping finished sales", () => {
  it("drops finished sales with nothing to say after an hour, and those with a note after a week", () => {
    const hour = 60 * 60_000;
    expect(expired(entry({ state: "done", doneAt: 0 }), hour + 1)).toBe(true);
    expect(expired(entry({ state: "done", doneAt: 0 }), hour)).toBe(false);
    expect(expired(entry({ state: "done", doneAt: 0, warnings: ["closed_day"] }), 24 * hour)).toBe(false);
    expect(expired(entry({ state: "done", doneAt: 0, warnings: ["closed_day"] }), 8 * 24 * hour)).toBe(true);
    expect(expired(entry({ state: "failed", doneAt: 0 }), 100 * 24 * hour)).toBe(false);
  });
});

describe("provisional numbers", () => {
  it("name the till and never repeat", () => {
    expect(provisionalNumber("D1", 7)).toBe("OFFLINE-D1-0007");
    expect(provisionalNumber("", 12345)).toBe("OFFLINE-TILL-12345");
  });
});
