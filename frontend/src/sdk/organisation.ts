import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";

/** Companies (with branches) the signed-in user can reach. Use it for company and branch pickers. */
export function useCompanies() {
  return useQuery({
    queryKey: ["companies"],
    queryFn: () => unwrap(api.GET("/api/v1/companies")),
    staleTime: 5 * 60_000,
  });
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
