import { useQuery } from "@tanstack/react-query";

import { opApi, opUnwrap } from "../../client";

/** Query keys of the Website area. Every one starts with "operator" so a change elsewhere can refresh them all. */
export const KEYS = {
  availability: ["operator", "site", "availability"],
  settings: ["operator", "site", "settings"],
  pages: ["operator", "site", "pages"],
  page: (id: string) => ["operator", "site", "page", id],
  versions: (id: string) => ["operator", "site", "versions", id],
  assets: ["operator", "site", "assets"],
  validate: ["operator", "site", "validate"],
  status: ["operator", "site", "status"],
  publishes: ["operator", "site", "publishes"],
  plans: ["operator", "site", "plans"],
} as const;

export function useAvailability() {
  return useQuery({ queryKey: KEYS.availability, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/availability")), staleTime: 300_000 });
}

export function useSettings() {
  return useQuery({ queryKey: KEYS.settings, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/settings")) });
}

export function useAssets() {
  return useQuery({ queryKey: KEYS.assets, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/assets")) });
}

export function useSiteStatus() {
  return useQuery({ queryKey: KEYS.status, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/status")) });
}
