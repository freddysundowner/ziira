import { useQuery } from "@tanstack/react-query";

import { opApi, opUnwrap } from "../../client";
import { useOperatorCan } from "../../me";

/** The dashboard's data, one query per section so each loads, fails and retries on its own. */
export function useDashboardQueries() {
  const seesTrail = useOperatorCan("platform.operators");
  return {
    overview: useQuery({ queryKey: ["operator", "dashboard"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/dashboard")) }),
    system: useQuery({ queryKey: ["operator", "dashboard-system"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/dashboard/system")), refetchInterval: 60_000 }),
    feed: useQuery({ queryKey: ["operator", "dashboard-feed"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/dashboard/feed")) }),
    trials: useQuery({
      queryKey: ["operator", "dashboard-trials"],
      queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/subscribers", { params: { query: { flag: "trial_ending", limit: 8 } } })),
    }),
    activity: useQuery({
      queryKey: ["operator", "dashboard-activity"],
      queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/audit", { params: { query: { limit: 10 } } })),
      enabled: seesTrail,
    }),
    seesTrail,
  };
}
