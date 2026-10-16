import { useQuery } from "@tanstack/react-query";

import { opApi, opUnwrap } from "./client";

/** Who is signed in to the console, and what their role allows (the server re-checks every call). */
export function useOperatorMe() {
  return useQuery({ queryKey: ["operator", "me"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/me")), staleTime: 60_000 });
}

/** True when the signed-in operator's role holds the permission. While unknown, nothing is allowed. */
export function useOperatorCan(permission: string): boolean {
  const me = useOperatorMe();
  return me.data?.permissions?.includes(permission) ?? false;
}
