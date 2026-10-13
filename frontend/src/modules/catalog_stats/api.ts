import { api, useQuery } from "@/sdk";

export interface CompanyCount {
  company_id: string;
  product_count: number;
}

/** Product counts kept by the plugin's backend. */
export function useCompanyCounts() {
  return useQuery({
    queryKey: ["catalog-stats"],
    queryFn: async () => ((await api.GET("/api/v1/plugins/catalog-stats")).data ?? []) as unknown as CompanyCount[],
  });
}
