/**
 * Sending the outbox. One sale at a time, oldest first, each with its own id so the server records it once however
 * often it is sent (a lost answer, a reload in the middle, two tabs at once). Pure of the browser: the store and the
 * way a sale is sent are passed in, which is how the tests run it.
 */
import { afterAttempt, nextToSend, type SendOutcome } from "./outbox";
import type { OutboxStore } from "./store";
import type { OutboxEntry } from "./types";

export interface SyncDeps {
  store: OutboxStore;
  send: (entry: OutboxEntry) => Promise<SendOutcome>;
  now: () => number;
  random?: () => number;
}

export interface DrainResult {
  accepted: number;
  rejected: number;
  /** A try failed for lack of an answer; the rest wait for the next round. */
  stoppedByError: boolean;
}

/** Sales left "sending" by a page that closed in the middle of a try are simply waiting again. */
export async function recoverInterrupted(store: OutboxStore): Promise<void> {
  for (const e of await store.list()) if (e.state === "sending") await store.patch(e.localId, { state: "pending" });
}

/** Send everything that is due. `force` ignores the retry timers (the cashier pressed "send now"). */
export async function drain(deps: SyncDeps, { force = false }: { force?: boolean } = {}): Promise<DrainResult> {
  const result: DrainResult = { accepted: 0, rejected: 0, stoppedByError: false };
  for (let guard = 0; guard < 10_000; guard++) {
    const entries = await deps.store.list();
    const now = deps.now();
    const view = force ? entries.map((e) => (e.state === "pending" ? { ...e, nextAttemptAt: 0 } : e)) : entries;
    const next = nextToSend(view, now);
    if (!next) break;
    await deps.store.patch(next.localId, { state: "sending" });
    let outcome: SendOutcome;
    try {
      outcome = await deps.send(next);
    } catch (error) {
      outcome = { kind: "retry", reason: (error as Error).message || "The sale could not be sent." };
    }
    await deps.store.patch(next.localId, afterAttempt(next, outcome, deps.now(), deps.random?.() ?? 0));
    if (outcome.kind === "accepted") result.accepted++;
    else if (outcome.kind === "rejected") result.rejected++;
    else { result.stoppedByError = true; break; }
  }
  return result;
}
