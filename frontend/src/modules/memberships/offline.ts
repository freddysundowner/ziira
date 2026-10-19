/**
 * The desk keeps working without a connection: a saved copy of who may come in (the roster), a queue of the check-ins made
 * meanwhile, and the rules to decide from the saved copy. Plain functions over plain data so they are easy to test; the
 * only side effects are the small read/write helpers at the bottom, which never throw when storage is blocked.
 */
import { readStored, writeStored } from "@/sdk";

/** One line of the roster the server sends (GET checkin/roster). */
export interface RosterEntry {
  number: string;
  card_number: string | null;
  outcome: string;
  code: string;
  message: string;
  plan: string | null;
  customer_id?: string | null;
  name?: string | null;
  phone?: string | null;
  photo_file_id?: string | null;
}

/** The roster as saved on this device. */
export interface SavedRoster {
  companyId: string;
  branchId: string;
  /** When it was saved (milliseconds since 1970). */
  savedAt: number;
  validHours: number;
  entries: RosterEntry[];
}

/** A check-in made while offline, waiting to be sent. */
export interface QueuedCheckin {
  local_id: string;
  identifier: string | null;
  customer_id: string | null;
  /** ISO time it happened. */
  occurred_at: string;
  /** How many times the server answered "not recorded" (it is dropped after MAX_TRIES). */
  tries: number;
}

export const MAX_TRIES = 3;
const HOUR = 3_600_000;

/** Whether a failed request is "could not reach the server" (the SDK turns that into a 503) rather than an answer. */
export function isNetworkFailure(error: unknown): boolean {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return true;
  if (error instanceof TypeError) return true;
  const status = (error as { status?: unknown } | null)?.status;
  return status === 503 || status === 502 || status === 504 || status === 0;
}

/** True while the saved copy may still be trusted. */
export function rosterIsValid(roster: SavedRoster | null | undefined, now: number): boolean {
  if (!roster) return false;
  return now - roster.savedAt <= roster.validHours * HOUR && now >= roster.savedAt - HOUR;
}

const norm = (text: string | null | undefined): string => (text ?? "").trim().toLowerCase();
const digits = (text: string | null | undefined): string => (text ?? "").replace(/\D/g, "");

/** Find the person whose member number or card number is exactly what was typed or scanned. */
export function findByIdentifier(entries: readonly RosterEntry[], text: string): RosterEntry | undefined {
  const wanted = norm(text);
  if (!wanted) return undefined;
  return entries.find((e) => norm(e.number) === wanted || (e.card_number !== null && norm(e.card_number) === wanted));
}

/** Names (every word typed must appear) or phone digits in the saved list; best matches first, at most `limit`. */
export function searchRoster(entries: readonly RosterEntry[], text: string, limit = 8): RosterEntry[] {
  const words = norm(text).split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const typedDigits = digits(text);
  const scored: { entry: RosterEntry; score: number }[] = [];
  for (const entry of entries) {
    const name = norm(entry.name);
    let score = -1;
    if (name && words.every((w) => name.includes(w))) score = name.startsWith(words[0] ?? "") ? 2 : 1;
    else if (typedDigits.length >= 4 && digits(entry.phone).includes(typedDigits)) score = 1;
    else if (norm(entry.number).includes(words.join(" "))) score = 0;
    if (score >= 0) scored.push({ entry, score });
  }
  scored.sort((a, b) => b.score - a.score || norm(a.entry.name).localeCompare(norm(b.entry.name)));
  return scored.slice(0, limit).map((s) => s.entry);
}

/** What the desk is told when it decides from the saved list. */
export interface OfflineDecision {
  outcome: "allow" | "warn" | "deny";
  allowed: boolean;
  code: string;
  message: string;
  /** Only an allowed or warned person is queued to be recorded when the connection returns. */
  queue: boolean;
}

export function decideFromRoster(entry: RosterEntry): OfflineDecision {
  const outcome = entry.outcome === "allow" || entry.outcome === "warn" ? entry.outcome : "deny";
  return { outcome, allowed: outcome !== "deny", code: entry.code, message: entry.message, queue: outcome !== "deny" };
}

// ---------------------------------------------------------------------------------------------------------- queue

/** A new queue item for a person decided offline. `id` and `now` are passed in so tests are exact. */
export function makeQueued(entry: RosterEntry, id: string, now: Date): QueuedCheckin {
  return { local_id: id, identifier: entry.number, customer_id: entry.customer_id ?? null, occurred_at: now.toISOString(), tries: 0 };
}

/** The queue with one more item (an item with the same local_id is not added twice). */
export function addToQueue(queue: readonly QueuedCheckin[], item: QueuedCheckin): QueuedCheckin[] {
  return queue.some((q) => q.local_id === item.local_id) ? [...queue] : [...queue, item];
}

export interface SyncAnswer { local_id: string; recorded: boolean }

/**
 * The queue after the server answered: recorded items go; an item the server did not record gets a try counted and goes after
 * MAX_TRIES. Items the server did not mention stay as they were. `dropped` is how many were given up on.
 */
export function afterSync(queue: readonly QueuedCheckin[], answers: readonly SyncAnswer[]): { queue: QueuedCheckin[]; recorded: number; dropped: number } {
  const byId = new Map(answers.map((a) => [a.local_id, a]));
  let recorded = 0;
  let dropped = 0;
  const left: QueuedCheckin[] = [];
  for (const item of queue) {
    const answer = byId.get(item.local_id);
    if (!answer) { left.push(item); continue; }
    if (answer.recorded) { recorded += 1; continue; }
    if (item.tries + 1 >= MAX_TRIES) { dropped += 1; continue; }
    left.push({ ...item, tries: item.tries + 1 });
  }
  return { queue: left, recorded, dropped };
}

// ---------------------------------------------------------------------------------------------------------- storage

const rosterKey = (branchId: string) => `ziira.memberships.roster.${branchId}`;
const queueKey = (branchId: string) => `ziira.memberships.queue.${branchId}`;
export const BRANCH_KEY = "ziira.memberships.branch";

export function readRoster(branchId: string): SavedRoster | null {
  const raw = readStored(rosterKey(branchId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as SavedRoster;
    return Array.isArray(parsed.entries) && typeof parsed.savedAt === "number" ? parsed : null;
  } catch {
    return null;
  }
}

export function saveRoster(roster: SavedRoster): void {
  writeStored(rosterKey(roster.branchId), JSON.stringify(roster));
}

export function readQueue(branchId: string): QueuedCheckin[] {
  const raw = readStored(queueKey(branchId));
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as QueuedCheckin[];
    return Array.isArray(parsed) ? parsed.filter((q) => typeof q.local_id === "string") : [];
  } catch {
    return [];
  }
}

export function saveQueue(branchId: string, queue: readonly QueuedCheckin[]): void {
  writeStored(queueKey(branchId), queue.length ? JSON.stringify(queue) : null);
}
