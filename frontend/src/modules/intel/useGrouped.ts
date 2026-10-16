import { api, type Schemas, unwrap, useQuery } from "@/sdk";

export type Grouped = Schemas["GroupedFindingsOut"];
export type Group = Schemas["FindingGroupOut"];
export type View = "open" | "waiting" | "done";
type Severity = "info" | "low" | "medium" | "high" | "critical";

/** The stored severities behind each word a business sees. */
export const BAND_SEVERITIES: Record<string, Severity[]> = { urgent: ["critical", "high"], soon: ["medium"], look: ["low", "info"] };

export interface GroupedFilters {
  /** Urgent, soon or worth a look. */
  band?: string;
  area?: string;
  companyId?: string;
  branchId?: string;
  search?: string;
  mine?: boolean;
  source?: string;
}

/** Things to look at as cards (similar ones together), most pressing first. */
export function useGrouped(view: View, limit: number, f: GroupedFilters = {}) {
  return useQuery({
    queryKey: ["intel", "grouped", view, limit, f],
    queryFn: () => unwrap(api.GET("/api/v1/intel/findings/grouped", {
      params: { query: {
        view, limit, severity: f.band ? BAND_SEVERITIES[f.band] : undefined, area: f.area || undefined, company_id: f.companyId || undefined,
        branch_id: f.branchId || undefined, search: f.search || undefined, assigned_to_me: f.mine || undefined, source: (f.source || undefined) as "connected" | "ziira" | undefined } },
    })),
    refetchInterval: 120_000,
  });
}
