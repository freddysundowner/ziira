import { api, unwrap, useQuery } from "@/sdk";

import { useBranch } from "../hooks";

/** The branch's live front-desk board, shared by the Home boxes "Free now" and "Checkouts waiting" (one request between them; same key as the front desk page). */
export function useDeskBoard() {
  const { branchId, zone } = useBranch();
  const board = useQuery({
    queryKey: ["bookings", "board", branchId], enabled: !!branchId, refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/front-desk/board", { params: { query: { branch_id: branchId } } })),
  });
  return { board, zone, ready: !!branchId };
}
