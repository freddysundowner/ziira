/** The outbox on disk (IndexedDB). The same small interface is implemented in memory for the tests. */
import { kvGet, kvSet, KV, OUTBOX, requestOf, transact } from "./idb";
import { expired, provisionalNumber } from "./outbox";
import type { OutboxEntry } from "./types";

export interface OutboxStore {
  list(): Promise<OutboxEntry[]>;
  patch(localId: string, change: Partial<OutboxEntry>): Promise<void>;
}

export interface NewSale {
  localId: string;
  tillId: string;
  branchId: string;
  userId: string;
  deviceId: string;
  deviceCode: string;
  madeAt: number;
  offsetMs: number;
  currency: string;
  /** Builds the rest of the entry once its number is known. */
  build: (number: string) => Pick<OutboxEntry, "total" | "op" | "lines" | "customerName" | "receipt">;
}

export const idbStore: OutboxStore = {
  async list() {
    return transact([OUTBOX], "readonly", (tx) => requestOf<OutboxEntry[]>(tx.objectStore(OUTBOX).getAll()));
  },
  async patch(localId, change) {
    await transact([OUTBOX], "readwrite", async (tx) => {
      const store = tx.objectStore(OUTBOX);
      const current = await requestOf<OutboxEntry | undefined>(store.get(localId));
      if (current) await requestOf(store.put({ ...current, ...change }));
    });
  },
};

/**
 * Put a sale in the outbox. The running numbers and the sale are written in one transaction, so a crash leaves either
 * the whole sale (with its number) or nothing; the cashier is told "saved" only after this resolves.
 * Writing the same `localId` twice keeps the first (a double tap on Complete cannot make two sales).
 */
export async function enqueue(sale: NewSale): Promise<OutboxEntry> {
  return transact([KV, OUTBOX], "readwrite", async (tx) => {
    const outbox = tx.objectStore(OUTBOX);
    const existing = await requestOf<OutboxEntry | undefined>(outbox.get(sale.localId));
    if (existing) return existing;
    const kv = tx.objectStore(KV);
    const seq = ((await requestOf<number | undefined>(kv.get("seq"))) ?? 0) + 1;
    const counterKey = `counter:${sale.deviceId}`;
    const n = ((await requestOf<number | undefined>(kv.get(counterKey))) ?? 0) + 1;
    await requestOf(kv.put(seq, "seq"));
    await requestOf(kv.put(n, counterKey));
    const number = provisionalNumber(sale.deviceCode, n);
    const entry: OutboxEntry = {
      localId: sale.localId, seq, state: "pending", tillId: sale.tillId, branchId: sale.branchId, userId: sale.userId, number,
      madeAt: sale.madeAt, offsetMs: sale.offsetMs, currency: sale.currency, ...sale.build(number),
      attempts: 0, nextAttemptAt: 0, lastAttemptAt: 0, lastError: "", warnings: [], serverNumber: "", saleId: "", doneAt: 0,
    };
    await requestOf(outbox.put(entry));
    return entry;
  });
}

export async function removeEntry(localId: string): Promise<void> {
  await transact([OUTBOX], "readwrite", async (tx) => { await requestOf(tx.objectStore(OUTBOX).delete(localId)); });
}

/** Forget finished sales that are old enough. */
export async function pruneDone(now: number): Promise<void> {
  const entries = await idbStore.list();
  for (const e of entries) if (expired(e, now)) await removeEntry(e.localId);
}

export async function readClock(): Promise<number> {
  return (await kvGet<number>("clock-offset")) ?? 0;
}
export async function writeClock(offsetMs: number): Promise<void> {
  await kvSet("clock-offset", offsetMs);
}
