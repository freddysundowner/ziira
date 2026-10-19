import { useState } from "react";

import { api, type Option, readStored, toast, unwrap, useCompany, useMutation, useQuery, useQueryClient, useSession, writeStored } from "@/sdk";

import type { Job, Stage } from "./types";

/** The company a Jobs screen works in, with its branches and currency. */
export function useJobsCompany() {
  const { company, companies, isLoading } = useCompany();
  return { company, companies, isLoading, companyId: company?.id ?? "", branches: company?.branches ?? [], currency: company?.currency };
}

/** The branch the person last worked in (remembered), else the first. */
export function useBranchChoice(branches: readonly { id: string }[]) {
  const [chosen, setChosen] = useState(() => readStored("ziira.jobs.branch") ?? "");
  const branchId = branches.some((b) => b.id === chosen) ? chosen : branches[0]?.id ?? "";
  return { branchId, setBranchId: (id: string) => { setChosen(id); writeStored("ziira.jobs.branch", id); } };
}

/** True when a unit is switched on for this business (optional links such as Customers and Point of Sale). */
export function useUnit(name: string): boolean {
  return useSession().enabledUnits.has(name);
}

export function useWorkflow(companyId: string, includeInactive = false) {
  return useQuery<Stage[]>({
    queryKey: ["jobs", "workflow", companyId, includeInactive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/workflow", { params: { query: { company_id: companyId, include_inactive: includeInactive } } })),
  });
}

export function usePeople() {
  return useQuery({ queryKey: ["jobs", "people"], staleTime: 5 * 60_000, queryFn: () => unwrap(api.GET("/api/v1/jobs/people")) });
}

export function useJobSettings(companyId: string) {
  return useQuery({
    queryKey: ["jobs", "settings", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/settings", { params: { query: { company_id: companyId } } })),
  });
}

export function useTemplates(companyId: string, onlyActive = false) {
  return useQuery({
    queryKey: ["jobs", "templates", companyId, onlyActive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/checklist-templates", { params: { query: { company_id: companyId, only_active: onlyActive } } })),
  });
}

export function useJob(jobId: string) {
  return useQuery({
    queryKey: ["jobs", "job", jobId],
    queryFn: () => unwrap(api.GET("/api/v1/jobs/jobs/{job_id}", { params: { path: { job_id: jobId } } })),
  });
}

/** Forget what the lists and board show, after anything changed. */
export function useRefreshJobs() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["jobs"] });
}

/**
 * A change to one job. Every job endpoint answers with the whole job, which replaces what the page holds,
 * so the screen shows what the server now says. Errors show as a toast (the global handler) unless the caller handles them.
 */
export function useJobAction<V = void>(jobId: string, call: (vars: V) => Promise<Job>, options?: { done?: string; silent?: boolean; onDone?: (job: Job) => void }) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    meta: options?.silent ? { silent: true } : undefined,
    onSuccess: (job) => {
      qc.setQueryData(["jobs", "job", jobId], job);
      void qc.invalidateQueries({ queryKey: ["jobs"], predicate: (q) => q.queryKey[1] !== "job" });
      if (options?.done) toast(options.done, "ok");
      options?.onDone?.(job);
    },
  });
}

export async function searchCustomers(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: text || undefined, limit: 20 } } }));
  return rows.map((c) => ({ value: c.id, label: c.name, hint: c.phone ?? c.code }));
}

export async function searchProducts(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text || undefined, limit: 20 } } }));
  return rows.map((p) => ({ value: p.id, label: p.name, hint: p.sku }));
}

export async function searchServiceItems(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text || undefined, limit: 40 } } }));
  return rows.filter((p) => p.product_type === "service").map((p) => ({ value: p.id, label: p.name, hint: p.sku }));
}

export async function searchAssets(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/jobs/assets", { params: { query: { search: text || undefined, limit: 20 } } }));
  return rows.map((a) => ({ value: a.id, label: a.label, hint: a.kind }));
}

export function useCustomer(id: string | null | undefined) {
  return useQuery({
    enabled: !!id, retry: false, staleTime: 60_000, queryKey: ["jobs", "customer", id],
    queryFn: () => unwrap(api.GET("/api/v1/crm/customers/{customer_id}", { params: { path: { customer_id: id ?? "" } } })),
  });
}

export function useProduct(id: string | null | undefined) {
  return useQuery({
    enabled: !!id, retry: false, staleTime: 5 * 60_000, queryKey: ["jobs", "product", id],
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: id ?? "" } } })),
  });
}

export function useAsset(id: string | null | undefined) {
  return useQuery({
    enabled: !!id, retry: false, staleTime: 60_000, queryKey: ["jobs", "asset-one", id],
    queryFn: () => unwrap(api.GET("/api/v1/jobs/assets/{asset_id}", { params: { path: { asset_id: id ?? "" } } })),
  });
}

/** A change to an estimate: it answers with the estimate, so the job (which lists its estimates) is read again. */
export function useEstimateAction<V, R>(call: (vars: V) => Promise<R>, options?: { done?: string; silent?: boolean; onDone?: (result: R) => void }) {
  const refresh = useRefreshJobs();
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

// --------------------------------------------------------------------------- the workshop's catalogue (data a business edits)
export function useWorkTypes(companyId: string, onlyActive = false) {
  return useQuery({
    queryKey: ["jobs", "work-types", companyId, onlyActive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/work-types", { params: { query: { company_id: companyId, only_active: onlyActive } } })),
  });
}

export function useLabourTasks(companyId: string, onlyActive = false) {
  return useQuery({
    queryKey: ["jobs", "labour-tasks", companyId, onlyActive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/labour-tasks", { params: { query: { company_id: companyId, only_active: onlyActive } } })),
  });
}

export function usePartCategories(companyId: string, onlyActive = false) {
  return useQuery({
    queryKey: ["jobs", "part-categories", companyId, onlyActive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/part-categories", { params: { query: { company_id: companyId, only_active: onlyActive } } })),
  });
}

export function useJobTypes(companyId: string, onlyActive = false) {
  return useQuery({
    queryKey: ["jobs", "job-types", companyId, onlyActive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/job-types", { params: { query: { company_id: companyId, only_active: onlyActive } } })),
  });
}

export function usePhotoCategories(companyId: string, onlyActive = false) {
  return useQuery({
    queryKey: ["jobs", "photo-categories", companyId, onlyActive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/photo-categories", { params: { query: { company_id: companyId, only_active: onlyActive } } })),
  });
}

export function useBays(companyId: string, branchId?: string, includeInactive = false) {
  return useQuery({
    queryKey: ["jobs", "bays", companyId, branchId ?? "", includeInactive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/bays", { params: { query: { company_id: companyId, branch_id: branchId || undefined, include_inactive: includeInactive } } })),
  });
}

export function usePackSteps(companyId: string) {
  return useQuery({
    queryKey: ["jobs", "pack-steps", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/pack-steps", { params: { query: { company_id: companyId } } })),
  });
}

/** What the item has been through before, shown when it comes in again. */
export function useVisits(assetId: string | null | undefined) {
  return useQuery({
    enabled: !!assetId, retry: false, queryKey: ["jobs", "visits", assetId],
    queryFn: () => unwrap(api.GET("/api/v1/jobs/assets/{asset_id}/visits", { params: { path: { asset_id: assetId ?? "" }, query: { limit: 6 } } })),
  });
}

/** A change to something that is not one job (a setting, a catalogue row): save, then read every Jobs list again. */
export function useCatalogAction<V, R>(call: (vars: V) => Promise<R>, options?: { done?: string; onDone?: (result: R) => void }) {
  const refresh = useRefreshJobs();
  return useMutation({
    mutationFn: call,
    onSuccess: (result) => {
      void refresh();
      if (options?.done) toast(options.done, "ok");
      options?.onDone?.(result);
    },
  });
}

/** Items marked as courtesy cars (kind "courtesy-car"), for lending one to a customer. */
export async function searchCourtesyCars(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/jobs/assets", { params: { query: { search: text || undefined, limit: 50 } } }));
  return rows.filter((a) => a.kind === "courtesy-car").map((a) => ({ value: a.id, label: a.label, hint: a.kind }));
}
