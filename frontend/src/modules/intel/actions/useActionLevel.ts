import { api, unwrap, useCan, useQuery } from "@/sdk";

/** The company's action level (1 to 4), or undefined when it is not known: reading settings needs `settings.manage`. */
export function useActionLevel(companyId: string | undefined): number | undefined {
  const canRead = useCan("settings.manage");
  const settings = useQuery({
    enabled: !!companyId && canRead, queryKey: ["company-settings", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId! } } })),
  });
  return settings.data?.intel_action_level;
}
