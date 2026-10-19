import { useCallback, useEffect, useRef, useState } from "react";

import { api, toast, unwrap, useDebounced, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { looksLikeIdentifier, viewFromRoster, viewFromServer, type ResultView } from "../gymLogic";
import {
  addToQueue, afterSync, decideFromRoster, findByIdentifier, isNetworkFailure, makeQueued, readQueue, readRoster, rosterIsValid, saveQueue, saveRoster,
  searchRoster, type QueuedCheckin, type RosterEntry, type SavedRoster,
} from "../offline";

/** One person the desk can pick: from the server's search or, offline, from the saved list. */
export interface Suggestion {
  key: string;
  customerId: string | null;
  name: string;
  number: string;
  phone: string | null;
  plan: string | null;
  status: string | null;
  owed: number;
  photoFileId: string | null;
  entry?: RosterEntry;
}

const fromEntry = (e: RosterEntry): Suggestion => ({
  key: e.number, customerId: e.customer_id ?? null, name: e.name ?? e.number, number: e.number, phone: e.phone ?? null, plan: e.plan, status: null, owed: 0,
  photoFileId: e.photo_file_id ?? null, entry: e,
});

/** Look people up by name, phone or number: on the server, or in the saved list when the server cannot be reached. */
export async function searchPeople(companyId: string, branchId: string, text: string): Promise<Suggestion[]> {
  try {
    const rows = await unwrap(api.GET("/api/v1/memberships/checkin/search", { params: { query: { company_id: companyId, q: text } } }));
    return rows.map((r) => ({
      key: r.customer_id, customerId: r.customer_id, name: r.name ?? r.number, number: r.number, phone: r.phone, plan: r.plan_name, status: r.membership_status,
      owed: Number(r.arrears ?? 0), photoFileId: r.photo_file_id,
    }));
  } catch (e) {
    if (!isNetworkFailure(e)) throw e;
    return searchRoster(readRoster(branchId)?.entries ?? [], text).map(fromEntry);
  }
}

/** Matches shown while the person types (from two letters). */
export function useSuggestions(companyId: string, branchId: string, text: string) {
  const typed = useDebounced(text.trim(), 250);
  return useQuery({
    enabled: !!companyId && typed.length >= 2, retry: false, staleTime: 10_000, queryKey: ["memberships", "checkin-search", companyId, typed],
    queryFn: () => searchPeople(companyId, branchId, typed),
  });
}

/** The saved copy of who may come in: refreshed on load and every ten minutes while online; kept on this device. */
export function useRoster(companyId: string, branchId: string) {
  const [saved, setSaved] = useState<SavedRoster | null>(() => (branchId ? readRoster(branchId) : null));
  useEffect(() => { setSaved(branchId ? readRoster(branchId) : null); }, [branchId]);
  const q = useQuery({
    enabled: !!companyId && !!branchId, retry: false, refetchOnWindowFocus: false, staleTime: 0, gcTime: 60_000, refetchInterval: 10 * 60_000,
    queryKey: ["memberships", "roster", companyId, branchId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/checkin/roster", { params: { query: { company_id: companyId, branch_id: branchId } } })),
  });
  const { data, dataUpdatedAt } = q;
  useEffect(() => {
    if (!data) return;
    const roster: SavedRoster = { companyId, branchId, savedAt: Date.now(), validHours: data.valid_hours, entries: data.entries };
    saveRoster(roster);
    setSaved(roster);
  }, [dataUpdatedAt]); // eslint-disable-line react-hooks/exhaustive-deps
  return { saved, error: q.error, refetch: q.refetch, loading: q.isLoading };
}

interface RunArgs { identifier?: string | null; customerId?: string | null; method?: "desk" | "scan"; override?: string }

/** The desk's work: decide a check-in, online or from the saved list, queue what was done offline and send it later. */
export function useDesk(companyId: string, branchId: string) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const [view, setView] = useState<ResultView | null>(null);
  const [choices, setChoices] = useState<Suggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [queue, setQueue] = useState<QueuedCheckin[]>([]);
  const syncing = useRef(false);

  const refreshed = () => { void qc.invalidateQueries({ queryKey: ["memberships", "checkin"] }); void qc.invalidateQueries({ queryKey: ["memberships", "summary"] }); };

  const blank = (headline: string, notFound: boolean): ResultView => ({
    outcome: "deny", headline, reasons: [], customerId: null, name: null, number: null, plan: null, photoUrl: null, owed: 0, creditsLeft: null, duplicate: false,
    overridden: false, canOverride: false, needsTerms: false, notFound, offlineSavedAt: null,
  });

  const decideOffline = (a: RunArgs, localId: string): ResultView => {
    const roster = readRoster(branchId);
    if (!roster || !rosterIsValid(roster, Date.now())) return blank(t("checkin.noSavedList"), false);
    const entry = a.customerId ? roster.entries.find((e) => e.customer_id === a.customerId) : a.identifier ? findByIdentifier(roster.entries, a.identifier) : undefined;
    if (!entry) return { ...blank(t("checkin.offlineNotFound"), true), offlineSavedAt: roster.savedAt };
    if (decideFromRoster(entry).queue) {
      const next = addToQueue(readQueue(branchId), makeQueued(entry, localId, new Date()));
      saveQueue(branchId, next);
      setQueue(next);
    }
    return viewFromRoster(entry, roster.savedAt);
  };

  const run = async (a: RunArgs): Promise<ResultView | null> => {
    if (!companyId || !branchId) return null;
    setBusy(true);
    setChoices(null);
    const localId = crypto.randomUUID();
    try {
      const res = await unwrap(api.POST("/api/v1/memberships/checkin", { body: {
        company_id: companyId, branch_id: branchId, identifier: a.identifier ?? null, customer_id: a.customerId ?? null, method: a.method ?? "desk",
        local_id: localId, override_reason: a.override ?? null, record: true } }));
      const v = viewFromServer(res);
      setView(v);
      refreshed();
      return v;
    } catch (e) {
      if (isNetworkFailure(e)) {
        const v = decideOffline(a, localId);
        setView(v);
        return v;
      }
      toast((e as Error).message, "bad");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const pick = (s: Suggestion) => run(s.customerId ? { customerId: s.customerId } : { identifier: s.number });

  /** What the receptionist typed, or a scanner typed and ended with Enter. */
  const submit = async (text: string, highlighted?: Suggestion, method: "desk" | "scan" = "desk") => {
    const typed = text.trim();
    if (!typed) return;
    if (looksLikeIdentifier(typed)) {
      const v = await run({ identifier: typed, method });
      if (v?.notFound) {
        const found = await searchPeople(companyId, branchId, typed).catch(() => []);
        if (found.length > 0) { setView(null); setChoices(found); }
      }
      return;
    }
    if (highlighted) { await pick(highlighted); return; }
    setBusy(true);
    try {
      const found = await searchPeople(companyId, branchId, typed);
      if (found.length === 1 && found[0]) await pick(found[0]);
      else if (found.length > 1) { setView(null); setChoices(found); }
      else setView(blank(t("checkin.nobodyFound"), true));
    } catch (e) {
      toast((e as Error).message, "bad");
    } finally {
      setBusy(false);
    }
  };

  const sync = useCallback(async () => {
    if (syncing.current || !companyId || !branchId) return;
    const waiting = readQueue(branchId);
    setQueue(waiting);
    if (waiting.length === 0) return;
    syncing.current = true;
    try {
      const batch = waiting.slice(0, 200);
      const res = await unwrap(api.POST("/api/v1/memberships/checkin/sync", { body: {
        company_id: companyId, branch_id: branchId,
        items: batch.map((i) => ({ local_id: i.local_id, identifier: i.identifier, customer_id: i.customer_id, method: "desk" as const, occurred_at: i.occurred_at })) } }));
      const after = afterSync(readQueue(branchId), res.results);
      saveQueue(branchId, after.queue);
      setQueue(after.queue);
      if (after.recorded > 0) toast(t("checkin.synced", { count: after.recorded }), "ok");
      if (after.dropped > 0) toast(t("checkin.syncDropped", { count: after.dropped }), "bad");
      void qc.invalidateQueries({ queryKey: ["memberships", "checkin"] });
    } catch (e) {
      if (!isNetworkFailure(e)) toast((e as Error).message, "bad");
    } finally {
      syncing.current = false;
    }
  }, [companyId, branchId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setQueue(branchId ? readQueue(branchId) : []);
    void sync();
    const again = () => void sync();
    window.addEventListener("online", again);
    const timer = window.setInterval(again, 60_000);
    return () => { window.removeEventListener("online", again); window.clearInterval(timer); };
  }, [branchId, sync]);

  const clear = () => { setView(null); setChoices(null); };
  return { view, choices, setChoices, busy, queue, submit, run, pick, sync, clear };
}

/** Today's counts and the latest entries (refreshed every half minute). */
export function useTodayAndRecent(companyId: string, branchId: string) {
  const enabled = !!companyId && !!branchId;
  const counts = useQuery({
    enabled, refetchInterval: 30_000, retry: false, queryKey: ["memberships", "checkin", "today", companyId, branchId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/checkin/today", { params: { query: { company_id: companyId, branch_id: branchId } } })),
  });
  const recent = useQuery({
    enabled, refetchInterval: 30_000, retry: false, queryKey: ["memberships", "checkin", "recent", companyId, branchId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/checkin/recent", { params: { query: { company_id: companyId, branch_id: branchId, limit: 20 } } })),
  });
  return { counts, recent };
}
