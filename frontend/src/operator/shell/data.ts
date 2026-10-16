import { useQuery } from "@tanstack/react-query";

import { opApi, opUnwrap } from "../client";

/** What needs an operator now. Read again every minute and when the window gets focus again. */
export function useAlerts() {
  return useQuery({
    queryKey: ["operator", "alerts"],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/alerts")),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

/** The set-up checklist, the environment and the risky settings that are on. */
export function useSetup() {
  return useQuery({ queryKey: ["operator", "setup"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/setup")), staleTime: 30_000 });
}

/** Server-side search for a typed text (two or more characters). */
export function useSearch(text: string) {
  return useQuery({
    queryKey: ["operator", "search", text],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/search", { params: { query: { q: text } } })),
    enabled: text.length >= 2,
    staleTime: 15_000,
    retry: false,
  });
}
