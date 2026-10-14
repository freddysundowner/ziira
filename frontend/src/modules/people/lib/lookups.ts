import { useMemo, useState } from "react";

import { api, type Option, unwrap, useCompany, useQuery } from "@/sdk";

import type { Employee } from "./types";

/** The company a screen works in (the user's first unless they pick another), its branches and its currency. */
export function useScope() {
  const { company: first, companies, isLoading } = useCompany();
  const [chosen, setChosen] = useState("");
  const company = companies.find((c) => c.id === chosen) ?? first;
  return { company, companies, companyId: company?.id ?? "", setCompanyId: setChosen, branches: company?.branches ?? [], currency: company?.currency, isLoading };
}

/** Everyone in a company by id, to put names on rows that carry only an employee id. */
export function useEmployeeDirectory(companyId: string) {
  const query = useQuery({
    enabled: !!companyId,
    queryKey: ["people", "directory", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/people/employees", { params: { query: { company_id: companyId, limit: 500 } } })),
    staleTime: 60_000,
  });
  const byId = useMemo(() => new Map((query.data ?? []).map((e) => [e.id, e])), [query.data]);
  return { ...query, byId, name: (id: string) => byId.get(id)?.full_name ?? "—" };
}

export const employeeOption = (e: Employee): Option => ({ value: e.id, label: e.full_name, hint: e.employee_no });

/** Server-side employee lookup for a Combobox. */
export const searchEmployees = (companyId: string, status?: "active") => async (text: string): Promise<Option[]> =>
  (await unwrap(api.GET("/api/v1/people/employees", { params: { query: { company_id: companyId || undefined, search: text || undefined, status, limit: 20 } } }))).map(employeeOption);

export function useDepartments(companyId: string) {
  return useQuery({
    enabled: !!companyId,
    queryKey: ["people", "departments", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/people/departments", { params: { query: { company_id: companyId } } })),
  });
}

export function useLeaveTypes(companyId: string) {
  return useQuery({
    enabled: !!companyId,
    queryKey: ["people", "leave-types", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/people/leave-types", { params: { query: { company_id: companyId } } })),
  });
}

export function usePayComponents(companyId: string, enabled = true) {
  return useQuery({
    enabled: !!companyId && enabled,
    queryKey: ["people", "components", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/people/pay-components", { params: { query: { company_id: companyId } } })),
  });
}

export function useRules(companyId: string, enabled = true) {
  return useQuery({
    enabled: !!companyId && enabled,
    queryKey: ["people", "rules", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/people/rules", { params: { query: { company_id: companyId } } })),
  });
}

export function useShifts(companyId: string, enabled = true) {
  return useQuery({
    enabled: !!companyId && enabled,
    queryKey: ["people", "shifts", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/people/shifts", { params: { query: { company_id: companyId } } })),
  });
}
