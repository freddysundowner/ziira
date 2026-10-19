import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addToQueue, afterSync, decideFromRoster, findByIdentifier, isNetworkFailure, makeQueued, MAX_TRIES, readQueue, readRoster, rosterIsValid, saveQueue,
  saveRoster, searchRoster, type RosterEntry, type SavedRoster,
} from "./offline";

const entry = (over: Partial<RosterEntry>): RosterEntry => ({
  number: "M-0001", card_number: null, outcome: "allow", code: "ok", message: "Welcome", plan: "Monthly", customer_id: "c1", name: "Jane Wanjiru", phone: "0712 345 678", ...over,
});
const list = [
  entry({}),
  entry({ number: "M-0002", card_number: "A9F3", name: "Peter Kamau", customer_id: "c2", phone: "0799000111" }),
  entry({ number: "M-0003", name: "Janet Otieno", customer_id: "c3", outcome: "deny", code: "expired", message: "Membership ended", phone: null }),
];
const roster = (savedAt: number, validHours = 24): SavedRoster => ({ companyId: "co", branchId: "b1", savedAt, validHours, entries: list });

describe("rosterIsValid", () => {
  it("is valid inside the hours the business allows and not after", () => {
    const t0 = Date.UTC(2026, 0, 1, 8);
    expect(rosterIsValid(roster(t0), t0 + 23 * 3_600_000)).toBe(true);
    expect(rosterIsValid(roster(t0), t0 + 25 * 3_600_000)).toBe(false);
    expect(rosterIsValid(roster(t0, 1), t0 + 2 * 3_600_000)).toBe(false);
  });
  it("is not valid when there is none", () => {
    expect(rosterIsValid(null, Date.now())).toBe(false);
  });
});

describe("findByIdentifier", () => {
  it("matches the member number or the card number, ignoring case and spaces", () => {
    expect(findByIdentifier(list, " m-0001 ")?.name).toBe("Jane Wanjiru");
    expect(findByIdentifier(list, "a9f3")?.number).toBe("M-0002");
  });
  it("finds nobody for an unknown or empty text", () => {
    expect(findByIdentifier(list, "M-9999")).toBeUndefined();
    expect(findByIdentifier(list, "  ")).toBeUndefined();
  });
});

describe("searchRoster", () => {
  it("finds names by every word typed, best start first", () => {
    expect(searchRoster(list, "jane w").map((e) => e.number)).toEqual(["M-0001"]);
    expect(searchRoster(list, "jan").map((e) => e.number)).toEqual(["M-0001", "M-0003"]);
    expect(searchRoster(list, "wanjiru jane").map((e) => e.number)).toEqual(["M-0001"]);
  });
  it("finds by the digits of a phone number", () => {
    expect(searchRoster(list, "0712345").map((e) => e.number)).toEqual(["M-0001"]);
  });
  it("returns nothing for nothing and respects the limit", () => {
    expect(searchRoster(list, "")).toEqual([]);
    expect(searchRoster(list, "j", 1)).toHaveLength(1);
  });
});

describe("decideFromRoster", () => {
  it("lets allow and warn in and queues them", () => {
    expect(decideFromRoster(entry({}))).toMatchObject({ outcome: "allow", allowed: true, queue: true });
    expect(decideFromRoster(entry({ outcome: "warn" }))).toMatchObject({ outcome: "warn", allowed: true, queue: true });
  });
  it("refuses and does not queue the rest", () => {
    expect(decideFromRoster(list[2] as RosterEntry)).toMatchObject({ outcome: "deny", allowed: false, queue: false, code: "expired" });
    expect(decideFromRoster(entry({ outcome: "something_new" })).allowed).toBe(false);
  });
});

describe("the queue", () => {
  const now = new Date("2026-03-01T09:30:00Z");
  it("adds an item once", () => {
    const item = makeQueued(list[0] as RosterEntry, "id-1", now);
    expect(item).toMatchObject({ local_id: "id-1", identifier: "M-0001", customer_id: "c1", occurred_at: "2026-03-01T09:30:00.000Z", tries: 0 });
    const once = addToQueue([], item);
    expect(addToQueue(once, item)).toHaveLength(1);
  });

  it("removes what the server recorded and keeps the rest", () => {
    const a = makeQueued(list[0] as RosterEntry, "a", now);
    const b = makeQueued(list[1] as RosterEntry, "b", now);
    const c = makeQueued(list[1] as RosterEntry, "c", now);
    const r = afterSync([a, b, c], [{ local_id: "a", recorded: true }, { local_id: "b", recorded: false }]);
    expect(r.recorded).toBe(1);
    expect(r.queue.map((q) => q.local_id)).toEqual(["b", "c"]);
    expect(r.queue[0]?.tries).toBe(1);
  });

  it("gives up on an item the server keeps refusing", () => {
    let queue = [makeQueued(list[0] as RosterEntry, "a", now)];
    let dropped = 0;
    for (let i = 0; i < MAX_TRIES; i++) {
      const r = afterSync(queue, [{ local_id: "a", recorded: false }]);
      queue = r.queue;
      dropped += r.dropped;
    }
    expect(queue).toEqual([]);
    expect(dropped).toBe(1);
  });
});

describe("storage", () => {
  beforeEach(() => {
    const data = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v); }, removeItem: (k: string) => { data.delete(k); },
    });
  });
  afterEach(() => vi.unstubAllGlobals());
  it("keeps the roster and the queue per branch", () => {
    saveRoster(roster(1_000));
    expect(readRoster("b1")?.entries).toHaveLength(3);
    expect(readRoster("other")).toBeNull();
    saveQueue("b1", [makeQueued(list[0] as RosterEntry, "a", new Date())]);
    expect(readQueue("b1")).toHaveLength(1);
    saveQueue("b1", []);
    expect(readQueue("b1")).toEqual([]);
  });
});

describe("isNetworkFailure", () => {
  it("recognises a server that could not be reached but not an answer", () => {
    expect(isNetworkFailure({ status: 503 })).toBe(true);
    expect(isNetworkFailure(new TypeError("Failed to fetch"))).toBe(true);
    expect(isNetworkFailure({ status: 403 })).toBe(false);
    expect(isNetworkFailure({ status: 422 })).toBe(false);
  });
});
