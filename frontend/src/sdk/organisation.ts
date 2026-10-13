import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

/** Companies (with branches) the signed-in user can reach. Use it for company and branch pickers. */
export function useCompanies() {
  return useQuery({
    queryKey: ["companies"],
    queryFn: async () => (await api.GET("/api/v1/companies")).data ?? [],
    staleTime: 5 * 60_000,
  });
}
