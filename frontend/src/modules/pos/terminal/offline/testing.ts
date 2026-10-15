/** Test helpers: outbox entries and an in-memory store. Not used by the app. */
import type { OutboxStore } from "./store";
import type { OutboxEntry } from "./types";

export function entry(over: Partial<OutboxEntry> = {}): OutboxEntry {
  const seq = over.seq ?? 1;
  return {
    localId: `sale-${seq}`, seq, state: "pending", tillId: "till-1", branchId: "branch-1", userId: "user-1", number: `OFFLINE-D1-${String(seq).padStart(4, "0")}`,
    madeAt: 1_000_000, offsetMs: 0, total: "116.00", currency: "KES",
    op: { type: "sale", local_id: `sale-${seq}`, till_session_id: "till-1", at: "2026-01-01T00:00:00.000Z", lines: [{ product_id: "p1", quantity: "1", unit_price: "116.00", discount: "0" }], payments: [{ method: "cash", amount: "116.00" }] },
    lines: [{ sku: "CEM", name: "Cement", quantity: "1", amount: "116.00" }], customerName: "",
    receipt: { title: "Receipt", number: "x", header: [], meta: [], lines: [], vat: [], totals: [], payments: [], notes: [], footer: [], is_copy: false },
    attempts: 0, nextAttemptAt: 0, lastAttemptAt: 0, lastError: "", warnings: [], serverNumber: "", saleId: "", doneAt: 0,
    ...over,
  };
}

export function memoryStore(initial: OutboxEntry[] = []): OutboxStore & { entries: Map<string, OutboxEntry> } {
  const entries = new Map(initial.map((e) => [e.localId, e]));
  return {
    entries,
    async list() { return [...entries.values()].map((e) => ({ ...e })); },
    async patch(localId, change) { const e = entries.get(localId); if (e) entries.set(localId, { ...e, ...change }); },
  };
}
