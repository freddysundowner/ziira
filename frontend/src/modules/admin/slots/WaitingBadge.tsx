import { useEffect } from "react";

import { api, setNavBadge, unwrap, useCan, useQuery } from "@/sdk";

/** Always mounted (shell.background): the count next to "Waiting for you" in the sidebar (approvals for me, plus open exceptions). */
export default function WaitingBadge() {
  const canApprove = useCan("approvals.decide");
  const canReview = useCan("exceptions.manage");
  const pending = useQuery({ enabled: canApprove, queryKey: ["approvals-pending"], refetchInterval: 120_000, queryFn: () => unwrap(api.GET("/api/v1/approvals/pending")) });
  const open = useQuery({ enabled: canReview, queryKey: ["exceptions-count"], refetchInterval: 120_000, queryFn: () => unwrap(api.GET("/api/v1/exceptions", { params: { query: { status: "open", limit: 100 } } })) });
  const count = (pending.data?.length ?? 0) + (open.data?.length ?? 0);
  useEffect(() => { setNavBadge("waiting", count); }, [count]);
  return null;
}
