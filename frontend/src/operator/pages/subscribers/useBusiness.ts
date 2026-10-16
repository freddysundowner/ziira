import { useQuery } from "@tanstack/react-query";

import { opApi, opUnwrap } from "../../client";

/** The business behind a subscriber: its units, support access and open support sessions. */
export function useBusiness(code: string) {
  return useQuery({
    queryKey: ["operator", "business", code],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/businesses/{code}", { params: { path: { code } } })),
  });
}
