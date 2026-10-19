import { useEffect, useState } from "react";

import { api, Combobox, Field, readStored, Select, type Option, type Schemas, unwrap, useCompany, useQuery, useTranslation, writeStored } from "@/sdk";

import { BRANCH_KEY } from "./offline";

/** Customers found as the person types (a membership is for an active customer). */
export async function searchCustomers(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: text || undefined, status: "active", limit: 20 } } }));
  return rows.map((c) => ({ value: c.id, label: c.name, hint: [c.code, c.phone].filter(Boolean).join(" · ") }));
}

/** Service items (products of type "service") found as the person types. */
export async function searchServices(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text || undefined, limit: 50 } } }));
  return rows.filter((p) => p.product_type === "service").slice(0, 20).map((p) => ({ value: p.id, label: p.name, hint: p.sku }));
}

export function CustomerPicker({ value, onChange, label, required, error }: {
  value: string; onChange: (id: string) => void; label?: string; required?: boolean; error?: string | null;
}) {
  const { t } = useTranslation("memberships");
  const current = useQuery({
    enabled: !!value, retry: false, staleTime: 5 * 60_000, queryKey: ["memberships-customer", value],
    queryFn: () => unwrap(api.GET("/api/v1/crm/customers/{customer_id}", { params: { path: { customer_id: value } } })),
  });
  return (
    <Field label={label ?? t("customer")} required={required} error={error}>
      <Combobox value={value} onChange={onChange} search={searchCustomers} selectedLabel={current.data?.name} placeholder={t("pickCustomer")} invalid={!!error} />
    </Field>
  );
}

export function ServicePicker({ value, onChange, label, hint, clearable }: {
  value: string; onChange: (id: string) => void; label: string; hint?: string; clearable?: boolean;
}) {
  const { t } = useTranslation("memberships");
  const current = useQuery({
    enabled: !!value, retry: false, staleTime: 5 * 60_000, queryKey: ["memberships-service", value],
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: value } } })),
  });
  return (
    <Field label={label} hint={hint}>
      <Combobox value={value} onChange={onChange} search={searchServices} selectedLabel={current.data?.name} placeholder={t("pickService")} clearable={clearable} />
    </Field>
  );
}

/** The branches of the company; a picker is shown only when there are several. Returns the chosen branch id and the field. */
export function useBranchChoice(companyId: string, chosen: string, onChange: (id: string) => void) {
  const { t } = useTranslation("memberships");
  const { companies } = useCompany(companyId || undefined);
  const company = companies.find((c) => c.id === companyId) ?? companies[0];
  const branches = company?.branches ?? [];
  const value = chosen || branches[0]?.id || "";
  const field = branches.length > 1
    ? (
        <Field label={t("branch")}>
          <Select value={value} onChange={(e) => onChange(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
        </Field>
      )
    : null;
  return { branchId: value, field };
}

/** Plans of the company, for a picker or a filter. */
export function usePlans(companyId?: string, status?: "active" | "retired") {
  return useQuery({
    queryKey: ["memberships-plans", companyId, status],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/plans", { params: { query: { company_id: companyId || undefined, status, limit: 200 } } })),
  });
}

/** Whether invoices can be issued from here (Point of sale and invoices are on). */
export function useInvoicing(): boolean | undefined {
  const q = useQuery({ queryKey: ["memberships-invoicing"], staleTime: 60_000, queryFn: () => unwrap(api.GET("/api/v1/memberships/invoicing")) });
  return q.data?.available;
}

export type Member = Schemas["MembershipOut"];
export type Plan = Schemas["MembershipPlanOut"];
export type PackageItem = Schemas["SessionPackageOut"];
export type SoldPackage = Schemas["SoldPackageOut"];
export type Schedule = Schemas["RecurringInvoiceOut"];
export type Run = Schemas["InvoiceRunOut"];
export type Entry = Schemas["CreditEntryOut"];

export type Profile = Schemas["MemberProfileOut"];
export type Settings = Schemas["MembershipSettingsOut"];

/**
 * The branch a desk works at: the one chosen last time on this device (when it still exists), else the first. A picker is
 * returned only when there are several branches.
 */
export function useDeskBranch(companyId: string) {
  const { t } = useTranslation("memberships");
  const { companies } = useCompany(companyId || undefined);
  const company = companies.find((c) => c.id === companyId) ?? companies[0];
  const branches = company?.branches ?? [];
  const [chosen, setChosen] = useState(() => readStored(BRANCH_KEY) ?? "");
  const branchId = branches.find((b) => b.id === chosen)?.id ?? branches[0]?.id ?? "";
  const choose = (id: string) => { setChosen(id); writeStored(BRANCH_KEY, id); };
  const field = branches.length > 1
    ? (
        <Select aria-label={t("branch")} className="min-w-44" value={branchId} onChange={(e) => choose(e.target.value)}>
          {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </Select>
      )
    : null;
  return { company, companyId: company?.id ?? "", branchId, branches, field };
}

/** Whether the browser believes it is online (it can still be wrong: requests decide). */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, []);
  return online;
}

/** The company's membership policies. */
export function useSettings(companyId?: string) {
  return useQuery({
    enabled: !!companyId, queryKey: ["memberships-settings", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/settings", { params: { query: { company_id: companyId ?? "" } } })),
  });
}
