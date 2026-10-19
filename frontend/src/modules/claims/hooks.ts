import { useState } from "react";

import { api, type Option, readStored, toast, unwrap, useCompany, useMutation, useQuery, useQueryClient, useSession, writeStored } from "@/sdk";

import type { AgeingRow, Claim, ClaimSummary, Owed, Payer, PayerStatement, Settings, ShortPay } from "./types";

/** The company a Claims screen works in, with its branches and currency. */
export function useClaimsCompany() {
  const { company, companies, isLoading } = useCompany();
  return { company, companies, isLoading, companyId: company?.id ?? "", branches: company?.branches ?? [], currency: company?.currency };
}

/** The branch the person last worked in (remembered), else the first. */
export function useBranchChoice(branches: readonly { id: string }[]) {
  const [chosen, setChosen] = useState(() => readStored("ziira.claims.branch") ?? "");
  const branchId = branches.some((b) => b.id === chosen) ? chosen : branches[0]?.id ?? "";
  return { branchId, setBranchId: (id: string) => { setChosen(id); writeStored("ziira.claims.branch", id); } };
}

/** True when a unit is switched on for this business (optional links such as Customers and Point of Sale). */
export function useUnit(name: string): boolean {
  return useSession().enabledUnits.has(name);
}

export function usePayers(companyId: string, onlyActive = false) {
  return useQuery<Payer[]>({
    queryKey: ["claims", "payers", companyId, onlyActive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/claims/payers", { params: { query: { company_id: companyId, only_active: onlyActive } } })),
  });
}

export function useClaimSettings(companyId: string) {
  return useQuery<Settings>({
    queryKey: ["claims", "settings", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/claims/settings", { params: { query: { company_id: companyId } } })),
  });
}

export function useClaim(claimId: string) {
  return useQuery<Claim>({
    queryKey: ["claims", "claim", claimId],
    queryFn: () => unwrap(api.GET("/api/v1/claims/claims/{claim_id}", { params: { path: { claim_id: claimId } } })),
  });
}

export interface ClaimFilters { status: string; payerId: string; search: string; branchId: string; waiting: string }
export const NO_FILTERS: ClaimFilters = { status: "", payerId: "", search: "", branchId: "", waiting: "" };

export function useClaimList(companyId: string, filters: ClaimFilters, search: string) {
  return useQuery<ClaimSummary[]>({
    queryKey: ["claims", "list", companyId, filters.status, filters.payerId, filters.branchId, search], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/claims/claims", { params: { query: {
      company_id: companyId, status: filters.status || undefined, payer_id: filters.payerId || undefined,
      branch_id: filters.branchId || undefined, search: search || undefined, limit: 200 } } })),
  });
}

/** The claim of a job or appointment, or null when there is none (the embedded panel). */
export function useClaimOfSource(sourceType: string, sourceId: string) {
  return useQuery<Claim | null>({
    queryKey: ["claims", "by-source", sourceType, sourceId], enabled: !!sourceId, retry: false,
    queryFn: async () => {
      const r = await api.GET("/api/v1/claims/claims/by-source", { params: { query: { source_type: sourceType, source_id: sourceId } } });
      if (r.response.status === 404) return null;
      return unwrap(Promise.resolve(r));
    },
  });
}

export function useAgeing(companyId: string) {
  return useQuery<AgeingRow[]>({
    queryKey: ["claims", "ageing", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/claims/ageing", { params: { query: { company_id: companyId } } })),
  });
}

export function useOwed(payerId: string, enabled = true) {
  return useQuery<Owed[]>({
    queryKey: ["claims", "owed", payerId], enabled: enabled && !!payerId,
    queryFn: () => unwrap(api.GET("/api/v1/claims/owed", { params: { query: { payer_id: payerId } } })),
  });
}

export function useShortPays(status?: string) {
  return useQuery<ShortPay[]>({
    queryKey: ["claims", "short-pays", status ?? "all"],
    queryFn: () => unwrap(api.GET("/api/v1/claims/short-pays", { params: { query: { status } } })),
  });
}

export function usePayerStatement(payerId: string) {
  return useQuery<PayerStatement>({
    queryKey: ["claims", "statement", payerId], enabled: !!payerId,
    queryFn: () => unwrap(api.GET("/api/v1/claims/payers/{payer_id}/statement", { params: { path: { payer_id: payerId } } })),
  });
}

/** Forget what the lists and reports show, after anything changed. */
export function useRefreshClaims() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["claims"] });
}

/**
 * A change to one claim. Most claim endpoints answer with the whole claim, which replaces what the page holds, so the
 * screen shows what the server now says. Errors show as a toast (the global handler) unless the caller handles them.
 */
export function useClaimAction<V = void>(claimId: string, call: (vars: V) => Promise<Claim>, options?: { done?: string; silent?: boolean; onDone?: (claim: Claim) => void }) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    meta: options?.silent ? { silent: true } : undefined,
    onSuccess: (claim) => {
      qc.setQueryData(["claims", "claim", claimId], claim);
      void qc.invalidateQueries({ queryKey: ["claims"], predicate: (q) => q.queryKey[1] !== "claim" });
      if (options?.done) toast(options.done, "ok");
      options?.onDone?.(claim);
    },
  });
}

/** A change that answers with something other than the claim (an estimate, a payer): everything is read again. */
export function useClaimsMutation<V, R>(call: (vars: V) => Promise<R>, options?: { done?: string; silent?: boolean; onDone?: (result: R) => void }) {
  const refresh = useRefreshClaims();
  return useMutation({
    mutationFn: call,
    meta: options?.silent ? { silent: true } : undefined,
    onSuccess: (result) => {
      void refresh();
      if (options?.done) toast(options.done, "ok");
      options?.onDone?.(result);
    },
  });
}

export async function searchCustomers(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: text || undefined, limit: 20 } } }));
  return rows.map((c) => ({ value: c.id, label: c.name, hint: c.phone ?? c.code }));
}

export async function searchServiceItems(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text || undefined, limit: 40 } } }));
  return rows.filter((p) => p.product_type === "service").map((p) => ({ value: p.id, label: p.name, hint: p.sku }));
}

export function useCustomer(id: string | null | undefined) {
  return useQuery({
    enabled: !!id, retry: false, staleTime: 60_000, queryKey: ["claims", "customer", id],
    queryFn: () => unwrap(api.GET("/api/v1/crm/customers/{customer_id}", { params: { path: { customer_id: id ?? "" } } })),
  });
}

/** Open the printable estimate in a new tab (a page the browser prints or saves as PDF). */
export async function openPrintable(estimateId: string): Promise<void> {
  const page = window.open("", "_blank");
  try {
    const html = await unwrap(api.GET("/api/v1/claims/estimates/{estimate_id}/document", { params: { path: { estimate_id: estimateId }, query: { format: "html" } }, parseAs: "text" }));
    if (!page) throw new Error("blocked");
    page.document.open();
    page.document.write(String(html));
    page.document.close();
    page.focus();
  } catch (error) {
    page?.close();
    throw error;
  }
}
