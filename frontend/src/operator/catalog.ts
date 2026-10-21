import { useQuery } from "@tanstack/react-query";

import { opApi, opUnwrap } from "./client";

/** Lookups several screens share (plan pickers, edition lists, unit names). They change rarely. */
export function usePlans() {
  return useQuery({ queryKey: ["operator", "plans"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/plans")), staleTime: 30_000 });
}

/** One plan with its prices (history and what is in force now). `code` empty waits. */
export function usePlanDetail(code: string) {
  return useQuery({
    queryKey: ["operator", "plan", code],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/plans/{code}", { params: { path: { code } } })),
    enabled: code !== "",
  });
}

export function useEditions() {
  return useQuery({ queryKey: ["operator", "editions"], queryFn: () => opUnwrap(opApi.GET("/api/v1/editions")), staleTime: 300_000 });
}

export function usePlatformUnits() {
  return useQuery({ queryKey: ["operator", "units"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/units")), staleTime: 30_000 });
}

/** Which units are sold on their own (one payment) and at what price: the platform's add-on catalogue for units. */
export function useUnitSales() {
  return useQuery({ queryKey: ["operator", "unit-sales"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/unit-sales")), staleTime: 30_000 });
}
