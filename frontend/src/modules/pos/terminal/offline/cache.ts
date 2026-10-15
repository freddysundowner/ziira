/**
 * The copy of what the till needs to sell without a connection, kept on the device for the till's branch: products with
 * the price in force and their tax rate and barcodes, tax codes, units, customers, mobile money accounts (names only),
 * reason lists and the receipt's header and footer. Fetched in the background whenever there is a connection; each part
 * that fails to load keeps its older copy.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api, unwrap } from "@/sdk";

import { trackedApi } from "./connectivity";
import { noteServerTime } from "./controller";
import { needsRefresh } from "./freshness";
import { useOnline } from "./hooks";
import { kvGet, kvSet } from "./idb";
import type { CatalogItem } from "./types";

export interface CachedCustomer {
  id: string;
  code: string;
  name: string;
  phone: string | null;
  creditLimit: string;
  paymentTermsDays: number;
}
export interface CachedAccount {
  id: string;
  name: string;
  branchId: string | null;
}
export interface CachedReason {
  id: string;
  label: string;
}

export interface TerminalCache {
  userId: string;
  branchId: string;
  fetchedAt: number;
  items: CatalogItem[];
  customers: CachedCustomer[];
  accounts: CachedAccount[];
  reasons: Record<string, CachedReason[]>;
  taxCodes: { id: string; code: string; name: string; vatRate: string }[];
  uoms: { id: string; code: string; name: string }[];
  receipt: { header: string[]; footer: string[] } | null;
}

export interface CacheScope {
  userId: string;
  branchId: string;
  locationId: string | null;
  customers: boolean;
  payments: boolean;
}

const PAGE = 500;
const MAX_ITEMS = 20_000;
export const cacheKey = (userId: string, branchId: string): string => `cache:${userId}:${branchId}`;

const empty = (scope: CacheScope): TerminalCache => ({
  userId: scope.userId, branchId: scope.branchId, fetchedAt: 0, items: [], customers: [], accounts: [], reasons: {}, taxCodes: [], uoms: [], receipt: null,
});

export async function loadCache(userId: string, branchId: string): Promise<TerminalCache | null> {
  try {
    return (await kvGet<TerminalCache>(cacheKey(userId, branchId))) ?? null;
  } catch {
    return null;
  }
}

async function allItems(scope: CacheScope): Promise<{ items: CatalogItem[]; date: string | null }> {
  const items: CatalogItem[] = [];
  let date: string | null = null;
  for (let offset = 0; offset < MAX_ITEMS; offset += PAGE) {
    const r = await trackedApi(api.GET("/api/v1/pos/catalog", {
      params: { query: { branch_id: scope.branchId, location_id: scope.locationId ?? undefined, limit: PAGE, offset } },
    }));
    date ??= r.response.headers.get("date");
    const page = await unwrap(Promise.resolve(r));
    items.push(...page);
    if (page.length < PAGE) break;
  }
  return { items, date };
}

async function allCustomers(): Promise<CachedCustomer[]> {
  const found: CachedCustomer[] = [];
  for (let offset = 0; offset < 5 * PAGE; offset += PAGE) {
    const page = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { status: "active", limit: PAGE, offset } } }));
    found.push(...page.map((c) => ({ id: c.id, code: c.code, name: c.name, phone: c.phone, creditLimit: String(c.credit_limit), paymentTermsDays: c.payment_terms_days })));
    if (page.length < PAGE) break;
  }
  return found;
}

/** Fetch every part; a part that fails keeps what was there. The first part (the products) decides whether the round counts as a refresh. */
export async function refreshCache(scope: CacheScope, previous: TerminalCache | null): Promise<TerminalCache> {
  const next: TerminalCache = { ...(previous ?? empty(scope)) };
  const { items, date } = await allItems(scope);       // throws when the server cannot be reached: nothing else is tried
  next.items = items;
  if (date) noteServerTime(date);
  const attempt = async (work: () => Promise<void>) => { try { await work(); } catch { /* keeps the older copy of this part */ } };
  await Promise.all([
    attempt(async () => { const r = await unwrap(api.GET("/api/v1/pos/receipt-settings", { params: { query: { branch_id: scope.branchId } } })); next.receipt = { header: r.header, footer: r.footer }; }),
    attempt(async () => {
      const rows = await unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category: "price_override" } } }));
      next.reasons = { ...next.reasons, price_override: rows.filter((r) => r.is_active).map((r) => ({ id: r.id, label: r.label })) };
    }),
    attempt(async () => {
      const rows = await unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category: "till_variance" } } }));
      next.reasons = { ...next.reasons, till_variance: rows.filter((r) => r.is_active).map((r) => ({ id: r.id, label: r.label })) };
    }),
    attempt(async () => { next.taxCodes = (await unwrap(api.GET("/api/v1/products/tax-codes"))).map((c) => ({ id: c.id, code: c.code, name: c.name, vatRate: String(c.vat_rate) })); }),
    attempt(async () => { next.uoms = (await unwrap(api.GET("/api/v1/products/uoms"))).map((u) => ({ id: u.id, code: u.code, name: u.name })); }),
    ...(scope.customers ? [attempt(async () => { next.customers = await allCustomers(); })] : []),
    ...(scope.payments ? [attempt(async () => {
      const rows = await unwrap(api.GET("/api/v1/payments/accounts"));
      next.accounts = rows.filter((a) => a.kind === "mobile_money" && a.is_active && (!a.branch_id || a.branch_id === scope.branchId))
        .map((a) => ({ id: a.id, name: a.name, branchId: a.branch_id }));
    })] : []),
  ]);
  next.fetchedAt = Date.now();
  await kvSet(cacheKey(scope.userId, scope.branchId), next);
  return next;
}

/** The terminal's cache: read from the device first, refreshed in the background when there is a connection. */
export function useTerminalCache(scope: CacheScope | null) {
  const online = useOnline();
  const [cache, setCache] = useState<TerminalCache | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const busy = useRef(false);
  const latest = useRef<TerminalCache | null>(null);
  latest.current = cache;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const key = scope ? cacheKey(scope.userId, scope.branchId) : "";

  useEffect(() => {
    let live = true;
    setLoaded(false);
    setCache(null);
    const s = scopeRef.current;
    if (s) void loadCache(s.userId, s.branchId).then((c) => { if (live) { setCache(c); setLoaded(true); } });
    return () => { live = false; };
  }, [key]);

  const refresh = useCallback(async () => {
    const s = scopeRef.current;
    if (!s || busy.current) return;
    busy.current = true;
    setRefreshing(true);
    try {
      setCache(await refreshCache(s, latest.current));
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      busy.current = false;
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!loaded || !key) return;
    const check = () => { if (needsRefresh(latest.current?.fetchedAt, Date.now(), online)) void refresh(); };
    check();
    const id = window.setInterval(check, 60_000);
    return () => window.clearInterval(id);
  }, [loaded, online, refresh, key]);

  return { cache, loaded, refreshing, failed, refresh };
}
