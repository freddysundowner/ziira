import { useEffect, useState } from "react";

import { api, readStored, unwrap, useCompany, useQuery, useQueryClient, useSession, writeStored } from "@/sdk";

import type { Offer, Resource } from "./types";

const BRANCH_KEY = "ziira.bookings.branch";

/** The branch a screen shows: the last one chosen, else the first. The company's time zone comes with it. */
export function useBranch() {
  const { company, companies, isLoading } = useCompany();
  const branches = company?.branches ?? [];
  const [chosen, setChosen] = useState(() => readStored(BRANCH_KEY) ?? "");
  const branchId = branches.some((b) => b.id === chosen) ? chosen : branches[0]?.id ?? "";
  const setBranchId = (id: string) => { setChosen(id); writeStored(BRANCH_KEY, id); };
  return { company, companies, companyId: company?.id ?? "", branches, branchId, setBranchId, zone: company?.timezone, currency: company?.currency, isLoading };
}

export function useResources(branchId: string, activeOnly = true) {
  return useQuery<Resource[]>({
    queryKey: ["bookings", "resources", branchId, activeOnly], enabled: !!branchId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/resources", { params: { query: { branch_id: branchId, active_only: activeOnly } } })),
  });
}

export function useOffers(companyId: string, activeOnly = true) {
  return useQuery<Offer[]>({
    queryKey: ["bookings", "offers", companyId, activeOnly], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/offers", { params: { query: { company_id: companyId, active_only: activeOnly } } })),
  });
}

/** The reasons of a list ("appointment_cancel", "appointment_reschedule") a person picks from. */
export function useReasons(category: "appointment_cancel" | "appointment_reschedule") {
  return useQuery({
    queryKey: ["bookings", "reasons", category], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category } } })),
  });
}

/** True when a unit is switched on for this business (optional links such as Customers and Point of Sale). */
export function useUnit(name: string): boolean {
  return useSession().enabledUnits.has(name);
}

/** Refresh everything Bookings shows after a change. */
export function useRefreshBookings() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["bookings"] });
}

/** A clock that ticks every minute (the current-time line). */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}
