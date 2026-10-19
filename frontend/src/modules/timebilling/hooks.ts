import { useState } from "react";

import { api, readStored, unwrap, useCompany, useQuery, useQueryClient, writeStored } from "@/sdk";

import type { Activity, Settings, Snippet, Staff, Template } from "./types";

const COMPANY_KEY = "ziira.timebilling.company";

/** The company a screen works in: the last one chosen, else the first. Most businesses have exactly one. */
export function useWorkCompany() {
  const { companies, isLoading } = useCompany();
  const [chosen, setChosen] = useState(() => readStored(COMPANY_KEY) ?? "");
  const company = companies.find((c) => c.id === chosen) ?? companies[0];
  const setCompanyId = (id: string) => { setChosen(id); writeStored(COMPANY_KEY, id); };
  return { company, companies, companyId: company?.id ?? "", currency: company?.currency, setCompanyId, isLoading };
}

export function useSettings(companyId: string) {
  return useQuery<Settings>({
    queryKey: ["timebilling", "settings", companyId], enabled: !!companyId, staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/settings", { params: { query: { company_id: companyId } } })),
  });
}

export function useStaff(companyId: string) {
  return useQuery<Staff[]>({
    queryKey: ["timebilling", "staff", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/staff", { params: { query: { company_id: companyId } } })),
  });
}

/** Refresh everything Time and Billing shows after a change. */
export function useRefresh() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["timebilling"] });
}

/** A client-made key for a request that must not be done twice. Made once per time a form opens; `renew` after a success. */
export function useRequestKey() {
  const [key, setKey] = useState(() => crypto.randomUUID());
  return { key, renew: () => setKey(crypto.randomUUID()) };
}

/** The names people pick for what they did (an accountant's "Bank reconciliation"), for suggestions on the task box. */
export function useActivities(companyId: string) {
  return useQuery<Activity[]>({
    queryKey: ["timebilling", "activities", companyId], enabled: !!companyId, staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/activities", { params: { query: { company_id: companyId } } })),
  });
}

export function useTemplates(companyId: string, includeInactive = false) {
  return useQuery<Template[]>({
    queryKey: ["timebilling", "templates", companyId, includeInactive], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/templates", { params: { query: { company_id: companyId, include_inactive: includeInactive } } })),
  });
}

export function useSnippets(companyId: string, kind?: "invoice_note" | "engagement_note") {
  return useQuery<Snippet[]>({
    queryKey: ["timebilling", "snippets", companyId, kind ?? ""], enabled: !!companyId, staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/snippets", { params: { query: { company_id: companyId, kind } } })),
  });
}
