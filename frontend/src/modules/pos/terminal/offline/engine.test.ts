import { describe, expect, it, vi } from "vitest";

import { drain, recoverInterrupted } from "./engine";
import type { SendOutcome } from "./outbox";
import { entry, memoryStore } from "./testing";

const accepted = (n: string): SendOutcome => ({ kind: "accepted", number: n, saleId: `id-${n}`, warnings: [], duplicate: false });

describe("sending the outbox", () => {
  it("sends every sale once, oldest first, and marks them done", async () => {
    const store = memoryStore([entry({ seq: 2 }), entry({ seq: 1 }), entry({ seq: 3 })]);
    const sent: string[] = [];
    const result = await drain({ store, now: () => 1000, send: async (e) => { sent.push(e.localId); return accepted(`N${e.seq}`); } });
    expect(sent).toEqual(["sale-1", "sale-2", "sale-3"]);
    expect(result).toEqual({ accepted: 3, rejected: 0, stoppedByError: false });
    expect([...store.entries.values()].every((e) => e.state === "done")).toBe(true);
    expect(store.entries.get("sale-2")).toMatchObject({ serverNumber: "N2", saleId: "id-N2" });
  });

  it("stops at the first lost connection and keeps everything: later sales wait their turn", async () => {
    const store = memoryStore([entry({ seq: 1 }), entry({ seq: 2 }), entry({ seq: 3 })]);
    const send = vi.fn(async (e: { seq: number }): Promise<SendOutcome> => (e.seq === 1 ? accepted("N1") : { kind: "retry", reason: "Cannot reach the server" }));
    const result = await drain({ store, now: () => 1000, send });
    expect(send).toHaveBeenCalledTimes(2);
    expect(result).toMatchObject({ accepted: 1, stoppedByError: true });
    expect(store.entries.get("sale-1")?.state).toBe("done");
    expect(store.entries.get("sale-2")).toMatchObject({ state: "pending", attempts: 1, nextAttemptAt: 1000 + 5000, lastError: "Cannot reach the server" });
    expect(store.entries.get("sale-3")).toMatchObject({ state: "pending", attempts: 0 });
  });

  it("does not try a sale again before its time, unless forced", async () => {
    const store = memoryStore([entry({ seq: 1, nextAttemptAt: 9000, attempts: 1 })]);
    const send = vi.fn(async (): Promise<SendOutcome> => accepted("N1"));
    await drain({ store, now: () => 1000, send });
    expect(send).not.toHaveBeenCalled();
    await drain({ store, now: () => 1000, send }, { force: true });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("a sale the server refuses is kept visible and does not hold the others back", async () => {
    const store = memoryStore([entry({ seq: 1 }), entry({ seq: 2 })]);
    const result = await drain({
      store, now: () => 1000,
      send: async (e) => (e.seq === 1 ? { kind: "rejected", reason: "Product not found" } : accepted("N2")),
    });
    expect(result).toEqual({ accepted: 1, rejected: 1, stoppedByError: false });
    expect(store.entries.get("sale-1")).toMatchObject({ state: "failed", lastError: "Product not found" });
    expect(store.entries.get("sale-2")?.state).toBe("done");
  });

  it("an exception while sending is a retry, not a lost sale", async () => {
    const store = memoryStore([entry({ seq: 1 })]);
    const result = await drain({ store, now: () => 0, send: async () => { throw new Error("boom"); } });
    expect(result.stoppedByError).toBe(true);
    expect(store.entries.get("sale-1")).toMatchObject({ state: "pending", lastError: "boom" });
  });

  it("sending the same outbox twice (a reload, two tabs) asks the server about each sale with its own id every time", async () => {
    const store = memoryStore([entry({ seq: 1 })]);
    const ids: string[] = [];
    // first try: the answer is lost on the way
    await drain({ store, now: () => 0, send: async (e) => { ids.push(e.op.local_id); return { kind: "retry", reason: "no answer" }; } });
    // second try, later: the server says it already had it
    await drain({ store, now: () => 60_000, send: async (e) => { ids.push(e.op.local_id); return { kind: "accepted", number: "N1", saleId: "s", warnings: [], duplicate: true }; } });
    expect(ids).toEqual(["sale-1", "sale-1"]);
    expect(store.entries.get("sale-1")?.state).toBe("done");
  });

  it("a sale left 'sending' by a page that closed is simply waiting again", async () => {
    const store = memoryStore([entry({ seq: 1, state: "sending" }), entry({ seq: 2, state: "done" }), entry({ seq: 3, state: "failed" })]);
    await recoverInterrupted(store);
    expect([...store.entries.values()].map((e) => e.state)).toEqual(["pending", "done", "failed"]);
  });
});
