import type { QueryClient } from "@tanstack/react-query";

/** After anything changes on a finding: every list, count and card is read again. */
export function refreshFindings(qc: QueryClient, findingId?: string): void {
  for (const key of ["findings", "grouped", "summary", "related"]) void qc.invalidateQueries({ queryKey: ["intel", key] });
  if (findingId) void qc.invalidateQueries({ queryKey: ["intel", "finding", findingId] });
}
