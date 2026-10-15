import { useQueryClient } from "@/sdk";

/** After a suggestion is decided: everything that shows suggestions, findings or the action log is stale. */
export function useRefreshActions(findingId?: string): () => void {
  const qc = useQueryClient();
  return () => {
    for (const key of [["intel", "proposals"], ["intel", "findings"], ["intel", "summary"], ["intel", "action-log"]]) void qc.invalidateQueries({ queryKey: key });
    if (findingId) void qc.invalidateQueries({ queryKey: ["intel", "finding", findingId] });
  };
}
