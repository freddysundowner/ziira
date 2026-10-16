import { useQuery } from "@tanstack/react-query";

import { useSyncExternalStore } from "react";

import { api, unwrap } from "./api";
import { getDisplayTimeZone, setDisplayTimeZone, subscribeDisplayTimeZone } from "./format";

/** Companies (with branches) the signed-in user can reach. Use it for company and branch pickers. */
export function useCompanies() {
  return useQuery({
    queryKey: ["companies"],
    queryFn: async () => {
      const companies = await unwrap(api.GET("/api/v1/companies"));
      setDisplayTimeZone(companies[0]?.timezone);       // every time shown is on the company's clock
      return companies;
    },
    staleTime: 5 * 60_000,
  });
}

/** The time zone times are shown in (changes once, when the company is first known): key a screen on it to redraw. */
export function useDisplayTimeZone(): string | undefined {
  return useSyncExternalStore(subscribeDisplayTimeZone, getDisplayTimeZone);
}

/** The company a screen works in: the one asked for, else the user's first. Most businesses have exactly one. */
export function useCompany(companyId?: string) {
  const { data, isLoading } = useCompanies();
  const company = data?.find((c) => c.id === companyId) ?? data?.[0];
  return { company, companies: data ?? [], isLoading };
}

/** Currency code of a company, for formatting its money. */
export function useCurrency(companyId?: string): string | undefined {
  return useCompany(companyId).company?.currency;
}
