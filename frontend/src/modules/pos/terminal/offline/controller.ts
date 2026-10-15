/**
 * The outbox as seen by the screens: one object for the whole browser tab, so the status chip, the queue screen and the
 * terminal all show the same thing. It loads the outbox from IndexedDB, sends it when it can (on reconnect, on a
 * timer, when a sale is added, when asked) and tells subscribers whenever something changed.
 */
import { api } from "@/sdk";

import { isOnline, reportReachable, subscribeConnectivity } from "./connectivity";
import { drain, recoverInterrupted } from "./engine";
import { probeStorage } from "./idb";
import { outcomeOf, retryNow, type SendOutcome } from "./outbox";
import { enqueue, idbStore, type NewSale, pruneDone, readClock, removeEntry, writeClock } from "./store";
import type { OutboxEntry } from "./types";

export interface OutboxState {
  /** The outbox has been read from disk. */
  ready: boolean;
  /** This browser can keep sales on the device. If not, selling without a connection is refused. */
  storageOk: boolean;
  entries: OutboxEntry[];
  /** A round of sending is running. */
  syncing: boolean;
}

const TICK_MS = 15_000;
let state: OutboxState = { ready: false, storageOk: true, entries: [], syncing: false };
const listeners = new Set<() => void>();
let started = false;
let running: Promise<void> | null = null;
let clockOffset = 0;

const emit = () => listeners.forEach((l) => l());
const set = (change: Partial<OutboxState>) => { state = { ...state, ...change }; emit(); };

export const getOutboxState = (): OutboxState => state;
export function subscribeOutbox(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** How far the server's clock was ahead of this device's the last time we heard from it (ms). */
export const serverOffsetMs = (): number => clockOffset;
export function noteServerTime(serverIso: string | null | undefined, receivedAt = Date.now()): void {
  const server = serverIso ? Date.parse(serverIso) : NaN;
  if (Number.isNaN(server)) return;
  clockOffset = server - receivedAt;
  void writeClock(clockOffset).catch(() => undefined);
}

async function reload(): Promise<void> {
  try {
    set({ entries: await idbStore.list(), storageOk: true });
  } catch {
    set({ storageOk: false });
  }
}

async function sendEntry(entry: OutboxEntry): Promise<SendOutcome> {
  try {
    const { data, error, response } = await api.POST("/api/v1/pos/sync/upload", { body: { ops: [entry.op] } });
    const received = Date.now();
    // The web layer answers "no connection" with a 503 of its own; a real 502-504 means the server is not answering either.
    reportReachable(![502, 503, 504].includes(response.status));
    noteServerTime(data?.server_time, received);
    return outcomeOf(response.status, data ?? error);
  } catch (error) {
    reportReachable(false);
    return { kind: "retry", reason: (error as Error).message || "Cannot reach the server." };
  }
}

async function round(force: boolean): Promise<void> {
  if (!state.storageOk) return;
  if (!isOnline() && !force) return;
  set({ syncing: true });
  try {
    await drain({
      store: { list: idbStore.list, patch: async (id, change) => { await idbStore.patch(id, change); await reload(); } },
      send: sendEntry, now: Date.now, random: Math.random,
    }, { force });
  } finally {
    await reload();
    set({ syncing: false });
  }
}

/** Send what is due now (`force`: ignore the retry timers). One round at a time; other tabs are kept out by a lock where the browser has one. */
export function syncNow(force = false): Promise<void> {
  if (running) return running;
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  const work = locks
    ? locks.request("ziira-pos-sync", { ifAvailable: true }, async (lock) => { if (lock) await round(force); }).then(() => undefined)
    : round(force);
  running = work.catch(() => undefined).finally(() => { running = null; });
  return running;
}

/** Start once per tab: read the outbox, then keep sending it. */
export function startOutbox(): void {
  if (started) return;
  started = true;
  void (async () => {
    const ok = await probeStorage();
    if (!ok) { set({ ready: true, storageOk: false }); return; }
    try {
      clockOffset = await readClock();
      await recoverInterrupted(idbStore);
      await pruneDone(Date.now());
      await reload();
    } catch {
      set({ storageOk: false });
    }
    set({ ready: true });
    await syncNow();
  })();
  subscribeConnectivity(() => { if (isOnline()) void syncNow(true); emit(); });
  window.setInterval(() => void syncNow(), TICK_MS);
}

/** Keep a sale on this device. Resolves only once it is safely stored; rejects when it cannot be (nothing is pretended). */
export async function addSale(sale: NewSale): Promise<OutboxEntry> {
  const entry = await enqueue(sale);
  await reload();
  void syncNow();
  return entry;
}

export async function retrySale(localId: string): Promise<void> {
  await idbStore.patch(localId, retryNow(Date.now()));
  await reload();
  void syncNow(true);
}

export async function dismissSale(localId: string): Promise<void> {
  await removeEntry(localId);
  await reload();
}
