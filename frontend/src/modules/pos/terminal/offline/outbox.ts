/** The outbox's rules as pure functions: order, retry timing, what the status chip says, how to read the server's answer. */
import type { ChipKind, Counts, OutboxEntry } from "./types";

export const RETRY_BASE_MS = 5_000;
export const RETRY_MAX_MS = 5 * 60_000;
/** Sales waiting longer than this, or this many at once, get a warning. */
export const OLD_AFTER_MS = 24 * 60 * 60_000;
export const LARGE_QUEUE = 50;

/** Wait before the next try after `attempts` failures: 5 s, 10 s, 20 s ... up to 5 minutes. `jitter` (0..1) spreads tills apart. */
export function retryDelay(attempts: number, jitter = 0): number {
  const n = Math.max(1, Math.floor(attempts));
  const base = Math.min(RETRY_BASE_MS * 2 ** (n - 1), RETRY_MAX_MS);
  return Math.round(base * (1 + 0.25 * Math.min(Math.max(jitter, 0), 1)));
}

export const bySeq = (entries: readonly OutboxEntry[]): OutboxEntry[] => [...entries].sort((a, b) => a.seq - b.seq);

const isWaiting = (e: OutboxEntry): boolean => e.state === "pending" || e.state === "sending";

/**
 * The next sale to send: the oldest one still waiting, if its time has come. Sales go in the order they were made,
 * so a sale waiting for its retry holds the later ones back (a lost connection would fail them all anyway).
 * Sales the server refused ("failed") do not hold anything back.
 */
export function nextToSend(entries: readonly OutboxEntry[], now: number): OutboxEntry | undefined {
  const first = bySeq(entries).find(isWaiting);
  return first && first.nextAttemptAt <= now ? first : undefined;
}

export function count(entries: readonly OutboxEntry[]): Counts {
  return {
    waiting: entries.filter(isWaiting).length,
    sending: entries.filter((e) => e.state === "sending").length,
    attention: entries.filter((e) => e.state === "failed").length,
    done: entries.filter((e) => e.state === "done").length,
  };
}

/** What the status chip in the terminal bar shows. Sales needing attention come first: they will not fix themselves. */
export function chipOf(counts: Counts, online: boolean): { kind: ChipKind; n: number } {
  if (counts.attention > 0) return { kind: "attention", n: counts.attention };
  if (online && counts.sending > 0) return { kind: "syncing", n: counts.waiting };
  if (counts.waiting > 0 && online) return { kind: "waiting", n: counts.waiting };
  if (!online) return { kind: "offline", n: counts.waiting };
  return { kind: "online", n: 0 };
}

export type OutboxWarning = "old" | "large";
export function outboxWarnings(entries: readonly OutboxEntry[], now: number): OutboxWarning[] {
  const waiting = entries.filter((e) => isWaiting(e) || e.state === "failed");
  const found: OutboxWarning[] = [];
  if (waiting.some((e) => now - e.madeAt > OLD_AFTER_MS)) found.push("old");
  if (waiting.length >= LARGE_QUEUE) found.push("large");
  return found;
}

/** Quantity per product in sales the server does not have yet, so the screen's stock figures keep counting them. */
export function reservedQuantities(entries: readonly OutboxEntry[], branchId: string): Map<string, number> {
  const reserved = new Map<string, number>();
  for (const e of entries) {
    if (e.branchId !== branchId || !isWaiting(e)) continue;
    for (const line of e.op.lines) reserved.set(line.product_id, (reserved.get(line.product_id) ?? 0) + Number(line.quantity));
  }
  return reserved;
}

/** What happened when a sale was sent. */
export type SendOutcome =
  | { kind: "accepted"; number: string; saleId: string; warnings: string[]; duplicate: boolean }
  /** The server read the sale and refused it: it needs a person. */
  | { kind: "rejected"; reason: string }
  /** No answer worth trusting (no connection, server trouble, signed out): the same sale is sent again later. */
  | { kind: "retry"; reason: string };

interface UploadBody {
  results?: { status?: string; number?: string | null; id?: string | null; warnings?: string[]; error?: string | null }[];
  message?: string;
}

/** Read the answer to one sale sent through the sync endpoint. */
export function outcomeOf(status: number, body: unknown): SendOutcome {
  const data = (body && typeof body === "object" ? body : {}) as UploadBody;
  if (status === 200) {
    const r = data.results?.[0];
    if (r?.status === "ok" || r?.status === "duplicate") {
      return { kind: "accepted", number: r.number ?? "", saleId: r.id ?? "", warnings: r.warnings ?? [], duplicate: r.status === "duplicate" };
    }
    if (r?.status === "rejected") return { kind: "rejected", reason: r.error || "The server could not accept this sale." };
    return { kind: "retry", reason: "The server's answer was not understood." };
  }
  const message = data.message || `The server answered ${status}.`;
  if (status === 401) return { kind: "retry", reason: "Signed out: sign in again to send." };
  if (status === 408 || status === 425 || status === 429 || status >= 500 || status === 0) return { kind: "retry", reason: message };
  return { kind: "rejected", reason: message };
}

/** The change to an entry after an attempt. */
export function afterAttempt(entry: OutboxEntry, outcome: SendOutcome, now: number, jitter = 0): Partial<OutboxEntry> {
  const base = { lastAttemptAt: now, attempts: entry.attempts + 1 };
  if (outcome.kind === "accepted") {
    return { ...base, state: "done", doneAt: now, lastError: "", warnings: outcome.warnings, serverNumber: outcome.number, saleId: outcome.saleId };
  }
  if (outcome.kind === "rejected") return { ...base, state: "failed", lastError: outcome.reason };
  return { ...base, state: "pending", lastError: outcome.reason, nextAttemptAt: now + retryDelay(base.attempts, jitter) };
}

/** A failed sale put back to be sent again right away. */
export const retryNow = (now: number): Partial<OutboxEntry> => ({ state: "pending", attempts: 0, nextAttemptAt: now, lastError: "" });

/** Finished sales are kept a while so their warnings can be read; the ones with nothing to say go sooner. */
export function expired(entry: OutboxEntry, now: number): boolean {
  if (entry.state !== "done") return false;
  const age = now - entry.doneAt;
  return entry.warnings.length === 0 ? age > 60 * 60_000 : age > 7 * 24 * 60 * 60_000;
}

/** The provisional number: the till's code and a running number that never repeats on this browser. */
export const provisionalNumber = (deviceCode: string, n: number): string => `OFFLINE-${deviceCode || "TILL"}-${String(n).padStart(4, "0")}`;
