import { useQuery } from "@tanstack/react-query";

import { api, type Option, unwrap, useCan } from "@/sdk";

/** Search functions for <Combobox search=...>: module-level so their identity is stable. */
export async function searchSuppliers(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/purchasing/suppliers", { params: { query: { search: text || undefined, status: "active", limit: 20 } } }));
  return rows.map((s) => ({ value: s.id, label: s.name, hint: s.code }));
}

export async function searchProducts(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text || undefined, limit: 20 } } }));
  return rows.map((p) => ({ value: p.id, label: p.name, hint: p.sku }));
}

export function useSupplier(id: string | null | undefined) {
  return useQuery({
    enabled: !!id, queryKey: ["purchasing", "supplier", id], staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/purchasing/suppliers/{supplier_id}", { params: { path: { supplier_id: id ?? "" } } })),
  });
}

export function useProduct(id: string | null | undefined) {
  return useQuery({
    enabled: !!id, queryKey: ["purchasing", "product", id], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: id ?? "" } } })),
  });
}

export function useReasons(category: string, enabled = true) {
  return useQuery({
    enabled, queryKey: ["purchasing", "reasons", category], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category } } })),
  });
}

/** Stock locations, when the Inventory unit is on and the user may see them; otherwise empty (the field is hidden). */
export function useLocations(companyId: string | undefined) {
  return useQuery({
    enabled: !!companyId, retry: false, queryKey: ["purchasing", "locations", companyId], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/inventory/locations", { params: { query: { company_id: companyId } } })),
  });
}

/** Cash, bank and mobile-money accounts that Payments offers for paying bills; empty when Payments is off. */
export function usePaymentAccounts(companyId: string | undefined) {
  return useQuery({
    enabled: !!companyId, retry: false, queryKey: ["purchasing", "pay-accounts", companyId], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/payments/accounts", { params: { query: { company_id: companyId } } })),
  });
}

/** Expense accounts for bill lines that are not goods; empty when Finance is off. */
export function useExpenseAccounts(companyId: string | undefined) {
  return useQuery({
    enabled: !!companyId, retry: false, queryKey: ["purchasing", "expense-accounts", companyId], staleTime: 5 * 60_000,
    queryFn: async () => (await unwrap(api.GET("/api/v1/finance/accounts", { params: { query: { company_id: companyId } } }))).filter((a) => a.type === "expense"),
  });
}

export function useTaxCodes() {
  return useQuery({ queryKey: ["tax-codes"], staleTime: 5 * 60_000, queryFn: () => unwrap(api.GET("/api/v1/products/tax-codes")) });
}

/** A pending approval for a document, if the signed-in user may decide it: the document's page then offers approve and reject. */
export function usePendingApproval(docType: string, docId: string, waiting: boolean) {
  const can = useCan("approvals.decide");
  return useQuery({
    enabled: waiting && can, retry: false, queryKey: ["purchasing", "approval", docType, docId],
    queryFn: async () => (await unwrap(api.GET("/api/v1/approvals/pending"))).find((r) => r.doc_type === docType && r.doc_id === docId) ?? null,
  });
}
